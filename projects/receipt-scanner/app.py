"""PixelScan Pro — the receipt archive, served to the phone on your own Wi-Fi.

    pip install -r requirements.txt
    python -m uvicorn app:app --host 0.0.0.0 --port 8000

Then open http://<this-machine's-ip>:8000 on the Pixel.

The shape of the thing:

    photograph  ->  stored  ->  read by Claude  ->  reviewed by a human  ->  filed

Storage comes second in that list and extraction third, which is the opposite of
the original. It matters: if extraction fails for any reason — no key, a rate
limit, an outage — the photograph is already on disk and the receipt is already
in the library, marked as unread. The paper can go in the bin regardless.
"""

from __future__ import annotations

import csv
import io
import os
import shutil
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Form, Request, UploadFile
from fastapi.responses import (
    FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import amounts
import auth
import db
import extract
import images
import retention

BASE = Path(__file__).parent
IMAGE_DIR = db.DATA_DIR / "images"
SESSION_COOKIE = "pixelscan_session"

#: Uploads larger than this are refused before Pillow is handed them.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

app = FastAPI(title="PixelScan Pro")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


# ------------------------------------------------------------------ helpers


def money(value: Decimal | None) -> str:
    """Money for display. A missing amount is an em dash, never '$0.00'."""
    return "—" if value is None else f"${value:,.2f}"


def plain(value: Decimal | None) -> str:
    """Money for a form field — no symbol, no thousands separator."""
    return "" if value is None else f"{value:.2f}"


def retention_label(receipt: db.Receipt) -> str:
    if receipt.retention_until is None:
        return "indefinitely" if receipt.has_warranty else "—"
    return receipt.retention_until.isoformat()


def parse_money_field(raw: str | None) -> Decimal | None:
    """Read what a person typed, with the same rules used on the paper.

    Typing ``10-`` into the tip box works here too, because it is the same
    function — one place where the convention lives.
    """
    value, _ = amounts.interpret_money(raw)
    return value


def get_db() -> sqlite3.Connection:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(get_db)]


def current_user(request: Request, conn: Conn) -> auth.User | None:
    return auth.session_user(conn, request.cookies.get(SESSION_COOKIE))


CurrentUser = Annotated["auth.User | None", Depends(current_user)]


def render(
    request: Request,
    template: str,
    conn: sqlite3.Connection,
    user: auth.User | None,
    **context: Any,
) -> HTMLResponse:
    counts = db.counts(conn)
    return templates.TemplateResponse(
        request=request,
        name=template,
        context={
            "user": user,
            "money": money,
            "plain": plain,
            "retention_label": retention_label,
            "queued": counts.get(db.STATUS_NEEDS_EXTRACTION, 0),
            "messages": [],
            **context,
        },
    )


def signin_redirect() -> RedirectResponse:
    return RedirectResponse("/signin", status_code=303)


def image_paths(receipt_id: str, when: date | None = None) -> tuple[Path, Path]:
    stamp = when or date.today()
    folder = IMAGE_DIR / f"{stamp.year:04d}" / f"{stamp.month:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{receipt_id}.jpg", folder / f"{receipt_id}_thumb.jpg"


def stored_name(path: Path) -> str:
    """The form kept in the database: relative to the image directory.

    Relative to IMAGE_DIR rather than to the project, so moving the archive —
    to another disk, or to a scratch directory for the self-tests — does not
    invalidate every row. Forward slashes so the value is not Windows-shaped.
    """
    return path.relative_to(IMAGE_DIR).as_posix()


def resolve_image(stored: str | None) -> Path | None:
    """Turn a stored name back into a path, refusing anything that escapes.

    The value came out of our own database, but it is still checked: a served
    file must never be able to climb out of the image directory.
    """
    if not stored:
        return None
    root = IMAGE_DIR.resolve()
    path = (root / stored).resolve()
    if not path.is_relative_to(root):
        return None
    return path


def remove_files(receipt: db.Receipt) -> None:
    for stored in (receipt.image_path, receipt.thumb_path):
        path = resolve_image(stored)
        if path is None:
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def api_key_present() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


# ------------------------------------------------------------------ auth


@app.get("/signin", response_class=HTMLResponse)
def signin_form(request: Request, conn: Conn):
    if auth.user_count(conn) == 0:
        return RedirectResponse("/setup", status_code=303)
    return templates.TemplateResponse(
        request=request, name="signin.html",
        context={"setup": False, "min_length": auth.MIN_PASSCODE_LENGTH},
    )


@app.post("/signin", response_class=HTMLResponse)
def signin(request: Request, conn: Conn,
           name: Annotated[str, Form()], passcode: Annotated[str, Form()]):
    try:
        user = auth.verify(conn, name, passcode)
    except auth.AuthError as exc:
        return templates.TemplateResponse(
            request=request, name="signin.html",
            context={"setup": False, "error": str(exc), "name": name,
                     "min_length": auth.MIN_PASSCODE_LENGTH},
            status_code=401,
        )
    return _start_session(conn, user, "/")


@app.get("/setup", response_class=HTMLResponse)
def setup_form(request: Request, conn: Conn):
    if auth.user_count(conn) > 0:
        return RedirectResponse("/signin", status_code=303)
    return templates.TemplateResponse(
        request=request, name="signin.html",
        context={"setup": True, "min_length": auth.MIN_PASSCODE_LENGTH},
    )


@app.post("/setup", response_class=HTMLResponse)
def setup(request: Request, conn: Conn,
          name: Annotated[str, Form()], passcode: Annotated[str, Form()]):
    if auth.user_count(conn) > 0:
        return RedirectResponse("/signin", status_code=303)
    try:
        user = auth.create_user(conn, name, passcode)
    except auth.AuthError as exc:
        return templates.TemplateResponse(
            request=request, name="signin.html",
            context={"setup": True, "error": str(exc), "name": name,
                     "min_length": auth.MIN_PASSCODE_LENGTH},
            status_code=400,
        )
    return _start_session(conn, user, "/")


def _start_session(conn: sqlite3.Connection, user: auth.User, target: str) -> RedirectResponse:
    token = auth.start_session(conn, user)
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=auth.SESSION_DAYS * 86400,
        httponly=True, samesite="lax",
    )
    return response


@app.post("/signout")
def signout(request: Request, conn: Conn):
    auth.end_session(conn, request.cookies.get(SESSION_COOKIE))
    response = RedirectResponse("/signin", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


# ------------------------------------------------------------------ library


@app.get("/", response_class=HTMLResponse)
def library(request: Request, conn: Conn, user: CurrentUser,
            q: str = "", view: str = "grid"):
    if user is None:
        return signin_redirect()
    receipts = db.search(conn, q)
    return render(request, "library.html", conn, user,
                  page="library", receipts=receipts, query=q,
                  view="table" if view == "table" else "grid")


@app.get("/export.csv")
def export_csv(conn: Conn, user: CurrentUser, q: str = ""):
    if user is None:
        return signin_redirect()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Date", "Company", "Account", "Amount", "Tip", "Subtotal",
                     "Tax", "Category", "Warranty", "Warranty item",
                     "Keep until", "Status"])
    for r in db.search(conn, q):
        writer.writerow([
            r.purchased_on.isoformat() if r.purchased_on else "",
            r.vendor or "", r.card_last4 or "",
            f"{r.total:.2f}" if r.total is not None else "",
            f"{r.tip:.2f}" if r.tip is not None else "",
            f"{r.subtotal:.2f}" if r.subtotal is not None else "",
            f"{r.tax:.2f}" if r.tax is not None else "",
            r.category or "", "YES" if r.has_warranty else "NO",
            r.warranty_note or "",
            r.retention_until.isoformat() if r.retention_until else "indefinitely",
            r.status,
        ])

    buffer.seek(0)
    stamp = datetime.now().strftime("%Y-%m-%d")
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename="pixelscan_{stamp}.csv"'},
    )


# ------------------------------------------------------------------ capture


@app.post("/scan")
async def scan(request: Request, conn: Conn, user: CurrentUser,
               photos: list[UploadFile] = []):
    """Take one or more photographs in, and never lose one.

    Each file is stored and given a database row *before* extraction is
    attempted. Extraction failing downgrades a receipt to 'queued'; it does not
    discard it.
    """
    if user is None:
        return signin_redirect()

    stored: list[str] = []
    failures: list[str] = []

    for upload in photos:
        if not upload.filename:
            continue
        payload = await upload.read()
        if not payload:
            continue
        if len(payload) > MAX_UPLOAD_BYTES:
            failures.append(
                f"{upload.filename}: {len(payload) // 1_048_576}MB is larger than "
                f"the {MAX_UPLOAD_BYTES // 1_048_576}MB limit"
            )
            continue

        try:
            image = images.open_normalized(payload)
        except ValueError as exc:
            failures.append(f"{upload.filename}: {exc}")
            continue

        receipt_id = db.create_pending(conn, image_path="", created_by=user.name)
        full_path, thumb_path = image_paths(receipt_id)
        full_path.write_bytes(images.for_archive(image))
        thumb_path.write_bytes(images.for_thumbnail(image))
        db.update(
            conn, receipt_id,
            image_path=stored_name(full_path),
            thumb_path=stored_name(thumb_path),
        )
        stored.append(receipt_id)

        run_extraction(conn, receipt_id, image)

    if failures and not stored:
        return render(request, "library.html", conn, user, page="library",
                      receipts=db.search(conn), query="", view="grid",
                      messages=[{"kind": "bad", "text": f} for f in failures])

    if len(stored) == 1:
        return RedirectResponse(f"/receipt/{stored[0]}", status_code=303)
    return RedirectResponse("/", status_code=303)


def run_extraction(
    conn: sqlite3.Connection,
    receipt_id: str,
    image=None,
) -> str | None:
    """Read one stored receipt. Returns an error message, or None on success.

    Never raises. A failure writes the real reason onto the row and leaves the
    receipt queued — which is the difference between "the API returned 529" and
    the original app's "Failed to process document."
    """
    receipt = db.get(conn, receipt_id)
    if receipt is None:
        return "receipt not found"

    if image is None:
        path = resolve_image(receipt.image_path)
        if path is None or not path.exists():
            message = "the stored image is missing"
            db.update(conn, receipt_id, extraction_error=message)
            return message
        try:
            image = images.open_normalized(path)
        except ValueError as exc:
            db.update(conn, receipt_id, extraction_error=str(exc))
            return str(exc)

    payload, media_type = images.for_model(image)
    try:
        result = extract.extract_from_bytes(payload, media_type)
    except extract.ExtractionError as exc:
        db.update(conn, receipt_id, extraction_error=str(exc))
        return str(exc)

    db.update(
        conn, receipt_id,
        status=db.STATUS_NEEDS_REVIEW,
        vendor=result.fields.vendor,
        purchased_on=result.purchased_on,
        subtotal_cents=db.to_cents(result.amounts["subtotal"]),
        tax_cents=db.to_cents(result.amounts["tax"]),
        tip_cents=db.to_cents(result.amounts["tip"]),
        total_cents=db.to_cents(result.amounts["total"]),
        card_last4=result.card_last4,
        payment_method=result.fields.payment_method,
        category=result.fields.category,
        has_warranty=result.fields.has_durable_goods,
        warranty_note=result.fields.durable_goods_note,
        transcript=result.fields.transcript,
        handwritten=result.fields.handwritten_amounts,
        extraction_model=result.model,
        extraction_json=result.fields.model_dump_json(),
        extraction_notes=result.notes,
        extraction_problems=result.problems,
        extraction_error=None,
    )
    return None


@app.get("/queue", response_class=HTMLResponse)
def queue(request: Request, conn: Conn, user: CurrentUser):
    if user is None:
        return signin_redirect()
    return render(request, "queue.html", conn, user,
                  page="queue", receipts=db.pending_extraction(conn))


@app.post("/queue/process", response_class=HTMLResponse)
def process_queue(request: Request, conn: Conn, user: CurrentUser):
    if user is None:
        return signin_redirect()

    read, errors = 0, []
    for receipt in db.pending_extraction(conn):
        error = run_extraction(conn, receipt.id)
        if error:
            errors.append(error)
            # One outage will fail every item identically. Stop rather than
            # hammer the API with the rest of the queue.
            if "rate limited" in error or "could not reach" in error:
                break
        else:
            read += 1

    messages = []
    if read:
        messages.append({"kind": "good", "text": f"Read {read} receipt(s)."})
    for error in dict.fromkeys(errors):
        messages.append({"kind": "bad", "text": error})

    return render(request, "queue.html", conn, user, page="queue",
                  receipts=db.pending_extraction(conn), messages=messages)


# ------------------------------------------------------------------ one receipt


@app.get("/receipt/{receipt_id}", response_class=HTMLResponse)
def receipt_page(request: Request, conn: Conn, user: CurrentUser, receipt_id: str):
    if user is None:
        return signin_redirect()
    receipt = db.get(conn, receipt_id)
    if receipt is None:
        return PlainTextResponse("No such receipt", status_code=404)

    if receipt.status == db.STATUS_FILED:
        return render(request, "detail.html", conn, user,
                      page="library", receipt=receipt)
    return review_page(request, conn, user, receipt)


@app.get("/receipt/{receipt_id}/edit", response_class=HTMLResponse)
def edit_page(request: Request, conn: Conn, user: CurrentUser, receipt_id: str):
    if user is None:
        return signin_redirect()
    receipt = db.get(conn, receipt_id)
    if receipt is None:
        return PlainTextResponse("No such receipt", status_code=404)
    return review_page(request, conn, user, receipt)


def review_page(request: Request, conn: sqlite3.Connection,
                user: auth.User, receipt: db.Receipt) -> HTMLResponse:
    problems = list(receipt.extraction_problems or [])
    notes = dict(receipt.extraction_notes or {})
    raw: dict[str, Any] = {}

    if receipt.extraction_error:
        problems.insert(0, receipt.extraction_error)

    import json
    row = conn.execute(
        "SELECT extraction_json FROM receipts WHERE id = ?", (receipt.id,)
    ).fetchone()
    if row and row["extraction_json"]:
        try:
            raw = json.loads(row["extraction_json"])
        except json.JSONDecodeError:
            raw = {}

    # Which form fields to highlight, derived from the problems rather than
    # restated, so a new check automatically lights up its own field.
    flagged: set[str] = set()
    for problem in problems:
        lowered = problem.lower()
        for name in ("tip", "total", "subtotal", "tax", "card_last4",
                     "vendor", "purchased_on"):
            if name.replace("_", " ") in lowered or name in lowered:
                flagged.add(name)
    if "date" in " ".join(problems).lower():
        flagged.add("purchased_on")

    preview_until, preview_reason = retention.retention_for(
        receipt.purchased_on or date.today(),
        receipt.has_warranty,
        receipt.warranty_months,
        receipt.category,
    )
    preview = (
        f"Kept until {preview_until.isoformat()} — {preview_reason}."
        if preview_until else f"Kept indefinitely — {preview_reason}."
    )

    duplicates = db.find_duplicates(
        conn, receipt.vendor, receipt.purchased_on, receipt.total,
        exclude_id=receipt.id,
    )

    return render(request, "review.html", conn, user,
                  page="library", receipt=receipt, problems=problems,
                  notes=notes, raw=raw, flagged=flagged,
                  categories=extract.CATEGORIES,
                  warranty_terms=retention.WARRANTY_TERMS,
                  retention_preview=preview, duplicates=duplicates)


@app.post("/receipt/{receipt_id}/save")
def save_receipt(
    conn: Conn, user: CurrentUser, receipt_id: str,
    vendor: Annotated[str, Form()] = "",
    purchased_on: Annotated[str, Form()] = "",
    subtotal: Annotated[str, Form()] = "",
    tax: Annotated[str, Form()] = "",
    tip: Annotated[str, Form()] = "",
    total: Annotated[str, Form()] = "",
    card_last4: Annotated[str, Form()] = "",
    payment_method: Annotated[str, Form()] = "",
    category: Annotated[str, Form()] = "Other",
    has_warranty: Annotated[str, Form()] = "",
    warranty_months: Annotated[str, Form()] = "",
    warranty_note: Annotated[str, Form()] = "",
):
    if user is None:
        return signin_redirect()

    try:
        purchase_date = date.fromisoformat(purchased_on) if purchased_on else date.today()
    except ValueError:
        purchase_date = date.today()

    warranty = bool(has_warranty)
    months = int(warranty_months) if warranty and warranty_months.isdigit() else None
    keep_until, reason = retention.retention_for(
        purchase_date, warranty, months, category
    )

    digits = "".join(c for c in card_last4 if c.isdigit())[-4:] or None

    db.update(
        conn, receipt_id,
        status=db.STATUS_FILED,
        vendor=vendor.strip() or None,
        purchased_on=purchase_date,
        subtotal_cents=db.to_cents(parse_money_field(subtotal)),
        tax_cents=db.to_cents(parse_money_field(tax)),
        tip_cents=db.to_cents(parse_money_field(tip)),
        total_cents=db.to_cents(parse_money_field(total)),
        card_last4=digits,
        payment_method=payment_method.strip() or None,
        category=category,
        has_warranty=warranty,
        warranty_months=months,
        warranty_note=warranty_note.strip() or None,
        retention_until=keep_until,
        retention_reason=reason,
        extraction_problems=[],
        extraction_error=None,
    )
    return RedirectResponse(f"/receipt/{receipt_id}", status_code=303)


@app.get("/receipt/{receipt_id}/reextract")
def reextract(conn: Conn, user: CurrentUser, receipt_id: str):
    if user is None:
        return signin_redirect()
    run_extraction(conn, receipt_id)
    return RedirectResponse(f"/receipt/{receipt_id}", status_code=303)


@app.get("/receipt/{receipt_id}/discard")
def discard(conn: Conn, user: CurrentUser, receipt_id: str):
    if user is None:
        return signin_redirect()
    receipt = db.delete(conn, receipt_id)
    if receipt:
        remove_files(receipt)
    return RedirectResponse("/", status_code=303)


@app.post("/receipt/{receipt_id}/delete")
def delete_receipt(conn: Conn, user: CurrentUser, receipt_id: str,
                   next: Annotated[str, Form()] = "/"):
    if user is None:
        return signin_redirect()
    receipt = db.delete(conn, receipt_id)
    if receipt:
        remove_files(receipt)
    return RedirectResponse(next if next.startswith("/") else "/", status_code=303)


@app.get("/image/{receipt_id}")
def receipt_image(conn: Conn, user: CurrentUser, receipt_id: str):
    return _send_image(conn, user, receipt_id, thumb=False)


@app.get("/thumb/{receipt_id}")
def receipt_thumb(conn: Conn, user: CurrentUser, receipt_id: str):
    return _send_image(conn, user, receipt_id, thumb=True)


def _send_image(conn: sqlite3.Connection, user: auth.User | None,
                receipt_id: str, thumb: bool):
    if user is None:
        return signin_redirect()
    receipt = db.get(conn, receipt_id)
    if receipt is None:
        return PlainTextResponse("No such receipt", status_code=404)

    path = resolve_image(receipt.thumb_path if thumb else receipt.image_path)
    if path is None or not path.exists():
        return PlainTextResponse("No image", status_code=404)
    return FileResponse(path, media_type="image/jpeg")


@app.get("/receipt/{receipt_id}/pdf")
def receipt_pdf(conn: Conn, user: CurrentUser, receipt_id: str):
    if user is None:
        return signin_redirect()
    receipt = db.get(conn, receipt_id)
    if receipt is None:
        return PlainTextResponse("No such receipt", status_code=404)

    import pdf as pdf_module

    payload = pdf_module.build(receipt, resolve_image(receipt.image_path) or Path("/nonexistent"))
    stamp = receipt.purchased_on.isoformat() if receipt.purchased_on else "undated"
    slug = "".join(c for c in (receipt.vendor or "receipt") if c.isalnum() or c in "-_")
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="{slug or "receipt"}_{stamp}.pdf"'},
    )


# ------------------------------------------------------------------ cleanup


@app.get("/cleanup", response_class=HTMLResponse)
def cleanup(request: Request, conn: Conn, user: CurrentUser):
    if user is None:
        return signin_redirect()
    due = db.expired(conn)
    total = db.counts(conn).get("total", 0)
    return render(request, "cleanup.html", conn, user, page="cleanup",
                  receipts=due, protected=total - len(due),
                  grace_days=retention.GRACE_DAYS)


@app.post("/cleanup/purge", response_class=HTMLResponse)
def purge(request: Request, conn: Conn, user: CurrentUser):
    if user is None:
        return signin_redirect()

    # Re-read rather than trusting anything posted. The only receipts that can
    # be deleted here are the ones the policy says are past their own date.
    removed = 0
    for receipt in db.expired(conn):
        deleted = db.delete(conn, receipt.id)
        if deleted:
            remove_files(deleted)
            removed += 1

    return render(request, "cleanup.html", conn, user, page="cleanup",
                  receipts=db.expired(conn),
                  protected=db.counts(conn).get("total", 0),
                  grace_days=retention.GRACE_DAYS,
                  messages=[{"kind": "good",
                             "text": f"Deleted {removed} receipt(s) past retention."}])


# ------------------------------------------------------------------ settings


@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request, conn: Conn, user: CurrentUser, error: str = ""):
    if user is None:
        return signin_redirect()
    return render(request, "settings.html", conn, user, page="settings",
                  users=auth.list_users(conn), stats=db.counts(conn),
                  model=extract.DEFAULT_MODEL, key_present=api_key_present(),
                  db_path=db.DB_PATH, image_dir=IMAGE_DIR,
                  default_years=retention.DEFAULT_YEARS,
                  grace_days=retention.GRACE_DAYS,
                  min_length=auth.MIN_PASSCODE_LENGTH, error=error)


@app.post("/settings/adduser", response_class=HTMLResponse)
def add_user(request: Request, conn: Conn, user: CurrentUser,
             name: Annotated[str, Form()], passcode: Annotated[str, Form()]):
    if user is None:
        return signin_redirect()
    try:
        auth.create_user(conn, name, passcode)
    except auth.AuthError as exc:
        return settings(request, conn, user, error=str(exc))
    return RedirectResponse("/settings", status_code=303)


@app.get("/healthz", response_class=PlainTextResponse)
def healthz(conn: Conn):
    counts = db.counts(conn)
    return (f"ok  receipts={counts.get('total', 0)}  "
            f"queued={counts.get(db.STATUS_NEEDS_EXTRACTION, 0)}  "
            f"model={extract.DEFAULT_MODEL}  key={'yes' if api_key_present() else 'no'}")


if __name__ == "__main__":
    import uvicorn

    print("PixelScan Pro")
    print(f"  database  {db.DB_PATH}")
    print(f"  images    {IMAGE_DIR}")
    print(f"  model     {extract.DEFAULT_MODEL}")
    print(f"  api key   {'found' if api_key_present() else 'NOT SET — scans will queue'}")
    print("  open      http://localhost:8000  (or this machine's LAN address)")
    uvicorn.run(app, host="0.0.0.0", port=8000)
