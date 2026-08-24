"""End-to-end walk through the whole app, against a throwaway archive.

Drives the real routes with a real HTTP client and a real SQLite file — sign in,
upload, queue, review, file, search, export, PDF, retention, delete. No mocks
for anything except the model call, which is stubbed so the loop can be checked
without a key or a network.

    python selftest_app.py

The one thing it cannot prove is whether Claude reads a crumpled thermal receipt
correctly. That needs photographs, and is measured separately.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

# Point the archive at a scratch directory *before* importing anything that
# reads it. Setting db.DB_PATH after the fact is not enough — app.py derives its
# own paths at import time — so the environment variable goes first.
_TMP = Path(tempfile.mkdtemp(prefix="pixelscan_selftest_"))
os.environ["PIXELSCAN_DATA"] = str(_TMP)

import app  # noqa: E402
import db  # noqa: E402
import extract  # noqa: E402
import make_fixture  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

assert db.DB_PATH.parent == _TMP, "self-test must not touch the real archive"
assert app.IMAGE_DIR.parent == _TMP, "self-test must not touch the real images"

failures = 0


def check(label: str, got, expected) -> None:
    global failures
    ok = got == expected
    failures += not ok
    shown = repr(got)
    if len(shown) > 46:
        shown = shown[:43] + "..."
    print(f"{'ok  ' if ok else 'FAIL'}  {label:<52} {shown}")


def stub_extraction(**fields):
    """Replace the network call with a fixed reading."""
    defaults = dict(
        vendor="The Angus Barn", purchased_on="2026-08-01",
        purchased_on_raw="08/01/26", subtotal_raw="42.00", tax_raw="3.36",
        tip_raw="10-", total_raw="55.36", card_last4="4242",
        payment_method="VISA", category="Restaurant", has_durable_goods=False,
        handwritten_amounts=True, uncertain_fields=[],
        transcript="THE ANGUS BARN\nRIBEYE 12OZ 38.00\nTIP 10-\nTOTAL 55.36",
    )
    defaults.update(fields)
    parsed = extract.ReceiptFields(**defaults)

    def fake(image_bytes, media_type=None, model=None, client=None):
        result = extract.interpret(parsed)
        result.model = "stub"
        result.input_tokens, result.output_tokens = 1500, 200
        return result

    extract.extract_from_bytes = fake


def fail_extraction(message: str):
    def fake(*args, **kwargs):
        raise extract.ExtractionError(message)

    extract.extract_from_bytes = fake


def main() -> int:
    make_fixture.SAMPLES = _TMP / "samples"
    restaurant = make_fixture.restaurant()
    hardware = make_fixture.hardware()

    client = TestClient(app.app, follow_redirects=False)

    print("first run and sign in")
    print("-" * 72)
    check("root sends a stranger to sign in",
          client.get("/").headers.get("location"), "/signin")
    check("signin bounces to setup when there are no users",
          client.get("/signin").headers.get("location"), "/setup")

    r = client.post("/setup", data={"name": "jason", "passcode": "testing123"})
    check("account created and signed in", r.status_code, 303)
    check("session cookie set", app.SESSION_COOKIE in client.cookies, True)

    r = client.get("/")
    check("library loads", r.status_code, 200)
    check("library is empty", "No receipts yet" in r.text, True)

    print()
    print("an outage — the photograph must survive it")
    print("-" * 72)
    fail_extraction("the Anthropic API returned 529: overloaded_error")
    with open(restaurant, "rb") as fh:
        r = client.post("/scan", files={"photos": ("receipt.png", fh, "image/png")})
    check("upload accepted despite extraction failing", r.status_code, 303)

    queued = db.pending_extraction(db.connect(db.DB_PATH))
    check("receipt exists anyway", len(queued), 1)
    check("marked as unread", queued[0].status, db.STATUS_NEEDS_EXTRACTION)
    check("the real error is recorded, not swallowed",
          "529" in (queued[0].extraction_error or ""), True)
    check("the image is on disk",
          app.resolve_image(queued[0].image_path).exists(), True)
    check("stored path cannot escape the image directory",
          app.resolve_image("../../../etc/passwd"), None)

    r = client.get("/queue")
    check("queue page lists it", "Process queue (1)" in r.text, True)

    print()
    print("draining the queue once the API is back")
    print("-" * 72)
    stub_extraction()
    r = client.post("/queue/process")
    check("queue processed", "Read 1 receipt" in r.text, True)
    check("queue now empty", len(db.pending_extraction(db.connect(db.DB_PATH))), 0)

    conn = db.connect(db.DB_PATH)
    receipt = db.search(conn)[0]
    check("awaiting review, not filed", receipt.status, db.STATUS_NEEDS_REVIEW)
    check("handwritten 10- became ten dollars", receipt.tip, Decimal("10.00"))
    check("total read", receipt.total, Decimal("55.36"))
    check("card reduced to last four", receipt.card_last4, "4242")

    r = client.get(f"/receipt/{receipt.id}")
    check("review screen shown for an unfiled receipt", r.status_code, 200)
    check("review shows how the tip was read",
          "trailing dash read as .00" in r.text, True)
    check("review says the amounts reconcile",
          "amounts reconcile" in r.text, True)

    print()
    print("filing it, with a warranty")
    print("-" * 72)
    r = client.post(f"/receipt/{receipt.id}/save", data={
        "vendor": "The Angus Barn", "purchased_on": "2026-08-01",
        "subtotal": "42.00", "tax": "3.36", "tip": "10-", "total": "55.36",
        "card_last4": "4242", "payment_method": "VISA",
        "category": "Restaurant", "warranty_months": "", "warranty_note": "",
    })
    check("saved", r.status_code, 303)

    conn = db.connect(db.DB_PATH)
    filed = db.get(conn, receipt.id)
    check("status filed", filed.status, db.STATUS_FILED)
    check("a typed '10-' is read the same way", filed.tip, Decimal("10.00"))
    check("no warranty -> two years", filed.retention_until, date(2028, 8, 1))
    check("retention explains itself",
          "no warranty item" in (filed.retention_reason or ""), True)

    r = client.get(f"/receipt/{receipt.id}")
    check("filed receipt shows the detail page", "Total charged" in r.text, True)

    print()
    print("a warranty receipt")
    print("-" * 72)
    stub_extraction(
        vendor="Lowe's", purchased_on="2026-03-17", purchased_on_raw="03/17/26",
        subtotal_raw="29.31", tax_raw="2.21", tip_raw=None, total_raw="31.52",
        card_last4="8557", category="Home Improvement", has_durable_goods=True,
        durable_goods_note="DeWalt 20V drill", handwritten_amounts=False,
        transcript="LOWE'S 1247\nDEWALT 20V DRILL 24.98\nTOTAL 31.52",
    )
    with open(hardware, "rb") as fh:
        r = client.post("/scan", files={"photos": ("lowes.png", fh, "image/png")})
    check("second receipt goes straight to review", r.status_code, 303)
    lowes_id = r.headers["location"].rsplit("/", 1)[-1]

    r = client.get(f"/receipt/{lowes_id}")
    check("warranty item was spotted", "DeWalt 20V drill" in r.text, True)
    check("no tip line means no review flag", "amounts reconcile" in r.text, True)

    client.post(f"/receipt/{lowes_id}/save", data={
        "vendor": "Lowe's", "purchased_on": "2026-03-17", "subtotal": "29.31",
        "tax": "2.21", "tip": "", "total": "31.52", "card_last4": "8557",
        "payment_method": "VISA", "category": "Home Improvement",
        "has_warranty": "1", "warranty_months": "120",
        "warranty_note": "DeWalt 20V drill",
    })
    conn = db.connect(db.DB_PATH)
    lowes = db.get(conn, lowes_id)
    check("ten year warranty retention", lowes.retention_until, date(2036, 6, 15))
    check("warranty term stored", lowes.warranty_months, 120)

    print()
    print("finding things again")
    print("-" * 72)
    check("search by vendor", len(db.search(conn, "angus")), 1)
    check("search by a word only in the transcript",
          len(db.search(conn, "dewalt")), 1)
    check("search by card digits", len(db.search(conn, "8557")), 1)
    r = client.get("/?q=lowe")
    check("search over HTTP", "Lowe" in r.text, True)
    r = client.get("/?view=table")
    check("table view renders", "<table" in r.text, True)

    r = client.get("/export.csv")
    check("csv exports", r.status_code, 200)
    check("csv has both receipts", r.text.strip().count("\n"), 2)
    check("csv carries the warranty item", "DeWalt 20V drill" in r.text, True)

    r = client.get(f"/receipt/{lowes_id}/pdf")
    check("pdf generated", r.content[:4], b"%PDF")
    check("pdf is a real size", len(r.content) > 5000, True)

    r = client.get(f"/image/{lowes_id}")
    check("image served", r.headers["content-type"], "image/jpeg")

    print()
    print("cleanup — the case the original got wrong")
    print("-" * 72)
    r = client.get("/cleanup")
    check("nothing due yet", "Nothing is past its retention" in r.text, True)

    # Backdate the restaurant receipt past its two years. The Lowe's receipt is
    # older still, but its warranty runs to 2036.
    db.update(conn, receipt.id, retention_until=date.today() - timedelta(days=1))
    conn = db.connect(db.DB_PATH)
    due = db.expired(conn)
    check("expired offers the restaurant receipt", len(due), 1)
    check("expired spares the warranty receipt",
          all(x.id != lowes_id for x in due), True)

    r = client.post("/cleanup/purge")
    check("purge ran", "Deleted 1 receipt" in r.text, True)
    conn = db.connect(db.DB_PATH)
    check("the warranty receipt is still here", db.get(conn, lowes_id) is not None, True)
    check("the expired one is gone", db.get(conn, receipt.id), None)

    print()
    print("access control")
    print("-" * 72)
    naked = TestClient(app.app, follow_redirects=False)
    check("library requires a session",
          naked.get("/").headers.get("location"), "/signin")
    check("an image requires a session",
          naked.get(f"/image/{lowes_id}").headers.get("location"), "/signin")
    check("export requires a session",
          naked.get("/export.csv").headers.get("location"), "/signin")
    check("wrong passcode refused",
          naked.post("/signin", data={"name": "jason", "passcode": "nope"}).status_code,
          401)

    r = client.post("/settings/adduser",
                    data={"name": "wife", "passcode": "another-one"})
    check("second account created", r.status_code, 303)
    r = client.get("/settings")
    check("both accounts listed", "wife" in r.text, True)
    check("settings warns when no API key is set",
          ("not set" in r.text) != app.api_key_present(), True)

    print()
    print("bad input")
    print("-" * 72)
    r = client.post("/scan", files={"photos": ("notes.txt", b"not an image", "text/plain")})
    check("a non-image is refused with a reason",
          "could not read this as an image" in r.text, True)
    check("nothing was stored for it", len(db.search(db.connect(db.DB_PATH))), 1)
    check("missing receipt is a 404", client.get("/receipt/nope").status_code, 404)

    conn.close()
    print()
    print(f"FAILURES: {failures}" if failures else "the whole loop holds")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    sys.exit(code)
