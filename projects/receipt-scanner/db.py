"""The archive: SQLite, on this machine, and nothing else.

Two decisions worth stating outright.

**Money is stored as integer cents.** Not floats. A receipt archive that cannot
add up to the penny is not an archive, and 0.1 + 0.2 is famously not 0.3.
Decimal goes in, cents are stored, Decimal comes back.

**A receipt exists before it has been read.** ``status`` starts at
``needs_extraction``: the photograph is on disk and the row is in the database
before the model is called at all. The original app extracted first and stored
second, so when the API failed it lost the photograph along with the fields —
which is precisely what happened during the outage. Here, the worst an API
failure can do is leave a row saying "not read yet".

Run this file directly to build a database and check the queries against it:

    python db.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

#: Where the archive lives. PIXELSCAN_DATA moves it — a different disk, an
#: encrypted volume, or a scratch directory for the self-tests.
DATA_DIR = Path(os.environ.get("PIXELSCAN_DATA") or Path(__file__).parent / "data")
DB_PATH = DATA_DIR / "receipts.db"

#: A receipt's life. It is filed only once a human has confirmed the fields.
STATUS_NEEDS_EXTRACTION = "needs_extraction"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_FILED = "filed"

MIGRATIONS: list[str] = [
    # 1 — receipts, users, sessions
    """
    CREATE TABLE receipts (
        id                 TEXT PRIMARY KEY,
        status             TEXT NOT NULL,
        vendor             TEXT,
        purchased_on       TEXT,
        subtotal_cents     INTEGER,
        tax_cents          INTEGER,
        tip_cents          INTEGER,
        total_cents        INTEGER,
        card_last4         TEXT,
        payment_method     TEXT,
        category           TEXT,
        has_warranty       INTEGER NOT NULL DEFAULT 0,
        warranty_months    INTEGER,
        warranty_note      TEXT,
        retention_until    TEXT,
        retention_reason   TEXT,
        image_path         TEXT NOT NULL,
        thumb_path         TEXT,
        transcript         TEXT,
        handwritten        INTEGER NOT NULL DEFAULT 0,
        extraction_model   TEXT,
        extraction_json    TEXT,
        extraction_notes   TEXT,
        extraction_problems TEXT,
        extraction_error   TEXT,
        created_by         TEXT,
        created_at         TEXT NOT NULL,
        updated_at         TEXT NOT NULL
    );
    CREATE INDEX idx_receipts_purchased ON receipts(purchased_on DESC);
    CREATE INDEX idx_receipts_status    ON receipts(status);
    CREATE INDEX idx_receipts_retention ON receipts(retention_until);

    CREATE TABLE users (
        id            TEXT PRIMARY KEY,
        name          TEXT NOT NULL UNIQUE,
        passcode_hash TEXT NOT NULL,
        salt          TEXT NOT NULL,
        created_at    TEXT NOT NULL,
        is_active     INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE sessions (
        token      TEXT PRIMARY KEY,
        user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    );
    CREATE INDEX idx_sessions_expiry ON sessions(expires_at);
    """,
    # 2 — full-text search over the transcript, so "the drill receipt" is
    #     findable by a word printed on the paper rather than only by vendor.
    """
    CREATE VIRTUAL TABLE receipts_fts USING fts5(
        vendor, category, transcript, warranty_note,
        content='receipts', content_rowid='rowid'
    );
    CREATE TRIGGER receipts_fts_insert AFTER INSERT ON receipts BEGIN
        INSERT INTO receipts_fts(rowid, vendor, category, transcript, warranty_note)
        VALUES (new.rowid, new.vendor, new.category, new.transcript, new.warranty_note);
    END;
    CREATE TRIGGER receipts_fts_delete AFTER DELETE ON receipts BEGIN
        INSERT INTO receipts_fts(receipts_fts, rowid, vendor, category, transcript, warranty_note)
        VALUES ('delete', old.rowid, old.vendor, old.category, old.transcript, old.warranty_note);
    END;
    CREATE TRIGGER receipts_fts_update AFTER UPDATE ON receipts BEGIN
        INSERT INTO receipts_fts(receipts_fts, rowid, vendor, category, transcript, warranty_note)
        VALUES ('delete', old.rowid, old.vendor, old.category, old.transcript, old.warranty_note);
        INSERT INTO receipts_fts(rowid, vendor, category, transcript, warranty_note)
        VALUES (new.rowid, new.vendor, new.category, new.transcript, new.warranty_note);
    END;
    """,
]


# ---------------------------------------------------------------- money


def to_cents(value: Decimal | int | float | None) -> int | None:
    if value is None:
        return None
    return int((Decimal(str(value)) * 100).to_integral_value(rounding="ROUND_HALF_UP"))


def from_cents(cents: int | None) -> Decimal | None:
    if cents is None:
        return None
    return (Decimal(cents) / 100).quantize(Decimal("0.01"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- connection


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open the archive, creating and migrating it if necessary.

    DB_PATH is read here rather than used as a default argument value. A default
    is bound once at import, so `db.DB_PATH = elsewhere` would silently have no
    effect on any caller that passes nothing — which is exactly how the first
    version of the self-test ended up writing into the real archive.
    """
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    # check_same_thread=False because FastAPI resolves a sync dependency in its
    # threadpool but runs an `async def` endpoint on the event loop, so the
    # connection is opened in one thread and used in another. Each request gets
    # its own connection and closes it again, so no connection is ever shared
    # between two requests — which is the condition the check exists to catch.
    conn = sqlite3.connect(path, detect_types=0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # Two requests writing at once (a scan finishing while the phone reloads
    # the library) should wait, not raise "database is locked".
    conn.execute("PRAGMA busy_timeout=5000")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """Apply any migrations this database has not seen. Returns the version.

    Principle 5, version everything — including the shape of the archive. A
    schema that changes without a record of what it used to be is a schema you
    cannot reason about six months later.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        " version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    current = row["v"] or 0

    for index, script in enumerate(MIGRATIONS[current:], start=current + 1):
        conn.executescript(script)
        conn.execute(
            "INSERT INTO schema_version(version, applied_at) VALUES (?, ?)",
            (index, _now()),
        )
        conn.commit()
    return len(MIGRATIONS)


# ---------------------------------------------------------------- receipts


@dataclass
class Receipt:
    """One receipt, with money as Decimal and dates as date."""

    id: str
    status: str
    image_path: str
    vendor: str | None = None
    purchased_on: date | None = None
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    tip: Decimal | None = None
    total: Decimal | None = None
    card_last4: str | None = None
    payment_method: str | None = None
    category: str | None = None
    has_warranty: bool = False
    warranty_months: int | None = None
    warranty_note: str | None = None
    retention_until: date | None = None
    retention_reason: str | None = None
    thumb_path: str | None = None
    transcript: str | None = None
    handwritten: bool = False
    extraction_model: str | None = None
    extraction_notes: dict[str, str] | None = None
    extraction_problems: list[str] | None = None
    extraction_error: str | None = None
    created_by: str | None = None
    created_at: str = ""
    updated_at: str = ""

    @property
    def needs_attention(self) -> bool:
        return self.status != STATUS_FILED


def _row_to_receipt(row: sqlite3.Row) -> Receipt:
    def as_date(value: str | None) -> date | None:
        return date.fromisoformat(value) if value else None

    def as_json(value: str | None, default: Any) -> Any:
        if not value:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default

    return Receipt(
        id=row["id"],
        status=row["status"],
        image_path=row["image_path"],
        vendor=row["vendor"],
        purchased_on=as_date(row["purchased_on"]),
        subtotal=from_cents(row["subtotal_cents"]),
        tax=from_cents(row["tax_cents"]),
        tip=from_cents(row["tip_cents"]),
        total=from_cents(row["total_cents"]),
        card_last4=row["card_last4"],
        payment_method=row["payment_method"],
        category=row["category"],
        has_warranty=bool(row["has_warranty"]),
        warranty_months=row["warranty_months"],
        warranty_note=row["warranty_note"],
        retention_until=as_date(row["retention_until"]),
        retention_reason=row["retention_reason"],
        thumb_path=row["thumb_path"],
        transcript=row["transcript"],
        handwritten=bool(row["handwritten"]),
        extraction_model=row["extraction_model"],
        extraction_notes=as_json(row["extraction_notes"], {}),
        extraction_problems=as_json(row["extraction_problems"], []),
        extraction_error=row["extraction_error"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def create_pending(
    conn: sqlite3.Connection,
    image_path: str,
    thumb_path: str | None = None,
    created_by: str | None = None,
) -> str:
    """Record a photograph that has not been read yet, and return its id.

    This is the first thing that happens after an upload, before the model is
    called. The paper can go in the bin the moment this returns.
    """
    receipt_id = uuid.uuid4().hex
    now = _now()
    conn.execute(
        "INSERT INTO receipts (id, status, image_path, thumb_path, created_by,"
        " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (receipt_id, STATUS_NEEDS_EXTRACTION, image_path, thumb_path,
         created_by, now, now),
    )
    conn.commit()
    return receipt_id


#: Columns a caller is allowed to write. Anything else raises, rather than
#: being silently dropped into a typo'd column that never gets read back.
WRITABLE = {
    "status", "vendor", "purchased_on", "subtotal_cents", "tax_cents",
    "tip_cents", "total_cents", "card_last4", "payment_method", "category",
    "has_warranty", "warranty_months", "warranty_note", "retention_until",
    "retention_reason", "image_path", "thumb_path", "transcript", "handwritten",
    "extraction_model", "extraction_json", "extraction_notes",
    "extraction_problems", "extraction_error", "created_by",
}


def update(conn: sqlite3.Connection, receipt_id: str, **fields: Any) -> None:
    """Write named columns. Decimals, dates, bools and containers are converted."""
    if not fields:
        return
    unknown = set(fields) - WRITABLE
    if unknown:
        raise ValueError(f"not writable columns: {sorted(unknown)}")

    prepared: dict[str, Any] = {}
    for key, value in fields.items():
        if isinstance(value, Decimal):
            prepared[key] = to_cents(value)
        elif isinstance(value, date):
            prepared[key] = value.isoformat()
        elif isinstance(value, bool):
            prepared[key] = int(value)
        elif isinstance(value, (dict, list)):
            prepared[key] = json.dumps(value)
        else:
            prepared[key] = value

    prepared["updated_at"] = _now()
    assignments = ", ".join(f"{k} = :{k}" for k in prepared)
    prepared["id"] = receipt_id
    conn.execute(f"UPDATE receipts SET {assignments} WHERE id = :id", prepared)
    conn.commit()


def get(conn: sqlite3.Connection, receipt_id: str) -> Receipt | None:
    row = conn.execute("SELECT * FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
    return _row_to_receipt(row) if row else None


def delete(conn: sqlite3.Connection, receipt_id: str) -> Receipt | None:
    """Remove a receipt, returning it so the caller can delete its image file."""
    receipt = get(conn, receipt_id)
    if receipt is None:
        return None
    conn.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,))
    conn.commit()
    return receipt


def _fts_query(search: str) -> str:
    """Turn user typing into an FTS5 prefix query, safely.

    FTS5 treats plenty of punctuation as syntax; a stray quote from a vendor
    name like Lowe's would otherwise raise instead of searching.
    """
    words = [w for w in "".join(
        c if c.isalnum() else " " for c in search
    ).split() if w]
    return " ".join(f'"{w}"*' for w in words)


def search(
    conn: sqlite3.Connection,
    query: str = "",
    status: str | None = None,
    limit: int = 500,
) -> list[Receipt]:
    """List receipts, newest purchase first, optionally filtered."""
    clauses: list[str] = []
    params: list[Any] = []

    if query.strip():
        fts = _fts_query(query)
        if fts:
            clauses.append(
                "(r.rowid IN (SELECT rowid FROM receipts_fts WHERE receipts_fts MATCH ?)"
                " OR r.card_last4 LIKE ?)"
            )
            params.extend([fts, f"%{query.strip()}%"])
    if status:
        clauses.append("r.status = ?")
        params.append(status)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT r.* FROM receipts r {where} "
        "ORDER BY COALESCE(r.purchased_on, r.created_at) DESC, r.created_at DESC "
        "LIMIT ?",
        (*params, limit),
    ).fetchall()
    return [_row_to_receipt(r) for r in rows]


def pending_extraction(conn: sqlite3.Connection) -> list[Receipt]:
    """Receipts whose photograph is safe but which have not been read.

    The queue behind the 'Process queue' action: everything a missing API key,
    a rate limit, or an outage left unread.
    """
    rows = conn.execute(
        "SELECT * FROM receipts WHERE status = ? ORDER BY created_at ASC",
        (STATUS_NEEDS_EXTRACTION,),
    ).fetchall()
    return [_row_to_receipt(r) for r in rows]


def expired(conn: sqlite3.Connection, today: date | None = None) -> list[Receipt]:
    """Receipts past their own retention date, and only those.

    NULL retention_until means keep indefinitely, and is excluded by the
    comparison rather than by an afterthought. There is no code path here that
    deletes by age alone — which is the bug that would have destroyed the
    ten-year-warranty receipts in the original.
    """
    cutoff = (today or date.today()).isoformat()
    rows = conn.execute(
        "SELECT * FROM receipts WHERE retention_until IS NOT NULL"
        " AND retention_until < ? ORDER BY retention_until ASC",
        (cutoff,),
    ).fetchall()
    return [_row_to_receipt(r) for r in rows]


def find_duplicates(
    conn: sqlite3.Connection,
    vendor: str | None,
    purchased_on: date | None,
    total: Decimal | None,
    exclude_id: str | None = None,
) -> list[Receipt]:
    """Same shop, same day, same amount — probably the same piece of paper."""
    if not (vendor and purchased_on and total is not None):
        return []
    rows = conn.execute(
        "SELECT * FROM receipts WHERE vendor = ? AND purchased_on = ?"
        " AND total_cents = ? AND id != ?",
        (vendor, purchased_on.isoformat(), to_cents(total), exclude_id or ""),
    ).fetchall()
    return [_row_to_receipt(r) for r in rows]


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM receipts GROUP BY status"
    ).fetchall()
    by_status = {r["status"]: r["n"] for r in rows}
    by_status["total"] = sum(by_status.values())
    return by_status


# ---------------------------------------------------------------- self test


def _self_test() -> int:
    import tempfile

    failures = 0

    def check(label: str, got: Any, expected: Any) -> None:
        nonlocal failures
        ok = got == expected
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {label:<46} {got!r}")

    with tempfile.TemporaryDirectory() as tmp:
        conn = connect(Path(tmp) / "test.db")
        check("migrations applied", migrate(conn), len(MIGRATIONS))

        # A photograph arrives. Nothing has been read yet.
        rid = create_pending(conn, "data/images/2026/03/x.jpg", created_by="jason")
        pending = pending_extraction(conn)
        check("pending after upload", len(pending), 1)
        check("status before extraction", pending[0].status, STATUS_NEEDS_EXTRACTION)

        # Extraction succeeds and a human files it.
        update(
            conn, rid,
            status=STATUS_FILED, vendor="Lowe's",
            purchased_on=date(2026, 3, 17),
            subtotal_cents=to_cents(Decimal("29.31")),
            tax_cents=to_cents(Decimal("2.21")),
            tip_cents=0, total_cents=to_cents(Decimal("31.52")),
            card_last4="8557", category="Home Improvement",
            has_warranty=True, warranty_months=36,
            warranty_note="DeWalt 20V drill",
            retention_until=date(2029, 6, 15),
            transcript="LOWE'S 1247 DEWALT 20V DRILL DRYWALL SCREWS",
        )
        got = get(conn, rid)
        check("total round-trips as Decimal", got.total, Decimal("31.52"))
        check("tip zero is not None", got.tip, Decimal("0.00"))
        check("warranty preserved", got.has_warranty, True)
        check("pending queue now empty", len(pending_extraction(conn)), 0)

        # Search, including a word only present in the transcript.
        check("search by vendor", len(search(conn, "lowe")), 1)
        check("search by transcript word", len(search(conn, "dewalt")), 1)
        check("search by card digits", len(search(conn, "8557")), 1)
        check("search miss", len(search(conn, "starbucks")), 0)
        check("apostrophe does not break FTS", len(search(conn, "Lowe's")), 1)

        # Retention: the case the original got wrong.
        coffee = create_pending(conn, "data/images/2026/03/c.jpg")
        update(conn, coffee, status=STATUS_FILED, vendor="Cafe",
               purchased_on=date(2026, 3, 17), total_cents=500,
               has_warranty=False, retention_until=date(2028, 3, 17))
        lifetime = create_pending(conn, "data/images/2026/03/l.jpg")
        update(conn, lifetime, status=STATUS_FILED, vendor="Lodge",
               purchased_on=date(2026, 3, 17), total_cents=4000,
               has_warranty=True, warranty_months=None, retention_until=None)

        # 1 June 2028. All three receipts are 2.2 years old, so the original
        # app's "delete anything older than 2 years" would have taken all
        # three — including the drill with a warranty running to 2029 and the
        # cast iron with no expiry at all. Only the coffee may go.
        offered = expired(conn, date(2028, 6, 1))
        check("expired offers the coffee", len(offered), 1)
        check("expired spares the warranty receipt",
              all(r.vendor != "Lowe's" for r in offered), True)
        check("expired spares the lifetime receipt",
              all(r.vendor != "Lodge" for r in offered), True)

        # And once the warranty plus its grace period has genuinely run out,
        # the same receipt is offered without any special case.
        later = expired(conn, date(2030, 1, 1))
        check("warranty receipt offered after its term", len(later), 2)

        # Duplicates.
        dupes = find_duplicates(conn, "Lowe's", date(2026, 3, 17), Decimal("31.52"))
        check("duplicate of itself excluded by id", len(dupes), 1)

        # Guard rails.
        try:
            update(conn, rid, notacolumn="x")
            check("unknown column rejected", False, True)
        except ValueError:
            check("unknown column rejected", True, True)

        check("counts", counts(conn)["total"], 3)
        conn.close()

    print()
    print(f"FAILURES: {failures}" if failures else "archive behaves")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
