"""The household schedule: SQLite, one file, and nothing else.

Four decisions worth stating outright.

**Every row carries a household_id, from migration 1.** Today there is exactly
one household in this database and no route can reach a second. That column is
not currently earning its keep — it is there because retrofitting multi-tenancy
onto a schema that assumed a single tenant is the expensive mistake, and the
stated horizon for this project is that other families use it one day.

**Times are stored as UTC ISO-8601 and rendered in the household timezone.**
Never local time in the column. A soccer season crosses a daylight-saving
boundary in November, and "5:30pm" stored as a naive string silently becomes
the wrong hour on one side of it.

**A repeating event is materialised into concrete rows**, one per occurrence,
sharing a series_id. Not an RRULE expanded at read time. The whole point of
this app is that individual occurrences change, and you need a real row to
attach "cancelled, rained out" to. Lazy expansion forces an exception model on
day one, which is where calendar code goes to die.

**A person and a contact are different things and never merge.** A person is in
the household and may have a login. A contact is another family's parent or a
coach: reachable by phone, never a user, never onboarded. That split is what
lets v0.1 ship without asking anyone else to install anything.

Run this file directly to build a database and check the queries against it:

    python db.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

#: Where the schedule lives. KIDLOG_DATA moves it — a different disk, or a
#: scratch directory for the self-tests.
DATA_DIR = Path(os.environ.get("KIDLOG_DATA") or Path(__file__).parent / "data")
DB_PATH = DATA_DIR / "kidlog.db"

# ---------------------------------------------------------------- vocabulary

KID = "kid"
ADULT = "adult"

#: What a person or contact is doing on an event. This is the mechanism the
#: whole app turns on — see changes.py. Adding a role here without teaching
#: changes.py what it means will raise there rather than silently drop someone.
ROLE_ATTENDING = "attending"        # a kid who goes
ROLE_DRIVING_THERE = "driving_there"
ROLE_DRIVING_HOME = "driving_home"
ROLE_CARPOOL = "carpool"            # another family whose kid shares the ride
ROLE_NOTIFY = "notify"              # affected but not riding: the coach

ROLES = (
    ROLE_ATTENDING,
    ROLE_DRIVING_THERE,
    ROLE_DRIVING_HOME,
    ROLE_CARPOOL,
    ROLE_NOTIFY,
)

DRIVING_ROLES = (ROLE_DRIVING_THERE, ROLE_DRIVING_HOME)

STATUS_ON = "on"
STATUS_CANCELLED = "cancelled"
STATUS_CHANGED = "changed"

#: Enough colours that two kids never collide, chosen to stay distinguishable
#: as a 10px dot on a phone in sunlight.
PALETTE = [
    "#2563eb",  # blue
    "#dc2626",  # red
    "#16a34a",  # green
    "#9333ea",  # purple
    "#ea580c",  # orange
    "#0891b2",  # teal
    "#db2777",  # pink
    "#ca8a04",  # amber
]

MIGRATIONS: list[str] = [
    # 1 — households, accounts, people, contacts, events, roles, changes.
    """
    CREATE TABLE households (
        id         TEXT PRIMARY KEY,
        name       TEXT NOT NULL,
        timezone   TEXT NOT NULL DEFAULT 'America/New_York',
        created_at TEXT NOT NULL
    );

    CREATE TABLE people (
        id           TEXT PRIMARY KEY,
        household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
        name         TEXT NOT NULL,
        kind         TEXT NOT NULL CHECK (kind IN ('kid','adult')),
        color        TEXT NOT NULL,
        initials     TEXT NOT NULL,
        phone        TEXT,
        checkin_url  TEXT,
        sort_order   INTEGER NOT NULL DEFAULT 0,
        is_active    INTEGER NOT NULL DEFAULT 1
    );
    CREATE INDEX idx_people_household ON people(household_id, is_active);

    -- person_id links an account to the household member it belongs to. It is
    -- what stops the app putting you on your own list of people to text, which
    -- is the fastest way to make a recipient list stop being trusted.
    CREATE TABLE users (
        id            TEXT PRIMARY KEY,
        household_id  TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
        person_id     TEXT REFERENCES people(id) ON DELETE SET NULL,
        name          TEXT NOT NULL UNIQUE,
        passcode_hash TEXT NOT NULL,
        salt          TEXT NOT NULL,
        platform      TEXT,
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

    CREATE TABLE contacts (
        id           TEXT PRIMARY KEY,
        household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
        name         TEXT NOT NULL,
        phone        TEXT,
        relation     TEXT,
        org          TEXT,
        checkin_url  TEXT,
        notes        TEXT,
        is_active    INTEGER NOT NULL DEFAULT 1
    );
    CREATE INDEX idx_contacts_household ON contacts(household_id, is_active);

    CREATE TABLE events (
        id               TEXT PRIMARY KEY,
        household_id     TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
        title            TEXT NOT NULL,
        starts_at_utc    TEXT NOT NULL,
        ends_at_utc      TEXT,
        location_name    TEXT,
        location_address TEXT,
        notes            TEXT,
        bring            TEXT,
        status           TEXT NOT NULL DEFAULT 'on'
                         CHECK (status IN ('on','cancelled','changed')),
        series_id        TEXT,
        created_by       TEXT,
        created_at       TEXT NOT NULL,
        updated_at       TEXT NOT NULL
    );
    CREATE INDEX idx_events_when   ON events(household_id, starts_at_utc);
    CREATE INDEX idx_events_series ON events(series_id);

    -- Exactly one of person_id / contact_id is set. A row that names both, or
    -- neither, is a bug in the caller and is rejected by the database rather
    -- than quietly producing a recipient nobody can be reached at.
    CREATE TABLE event_people (
        id         TEXT PRIMARY KEY,
        event_id   TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        person_id  TEXT REFERENCES people(id) ON DELETE CASCADE,
        contact_id TEXT REFERENCES contacts(id) ON DELETE CASCADE,
        role       TEXT NOT NULL,
        CHECK ((person_id IS NULL) <> (contact_id IS NULL))
    );
    CREATE INDEX idx_event_people_event  ON event_people(event_id);
    CREATE INDEX idx_event_people_person ON event_people(person_id);

    CREATE TABLE changes (
        id              TEXT PRIMARY KEY,
        event_id        TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        reason          TEXT NOT NULL,
        note            TEXT,
        made_by         TEXT,
        made_at         TEXT NOT NULL,
        recipients_json TEXT NOT NULL,
        told_json       TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX idx_changes_event ON changes(event_id, made_at DESC);
    """,
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------- connection


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open the schedule, creating and migrating it if necessary.

    DB_PATH is read here rather than used as a default argument value. A default
    is bound once at import, so `db.DB_PATH = elsewhere` would silently have no
    effect on any caller that passes nothing.
    """
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    # check_same_thread=False because FastAPI resolves a sync dependency in its
    # threadpool but runs an `async def` endpoint on the event loop. Each
    # request opens and closes its own connection, so none is ever shared.
    conn = sqlite3.connect(path, detect_types=0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """Apply any migrations this database has not seen. Returns the version."""
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


# ---------------------------------------------------------------- records


@dataclass
class Person:
    id: str
    household_id: str
    name: str
    kind: str
    color: str
    initials: str
    phone: str | None = None
    checkin_url: str | None = None
    sort_order: int = 0
    is_active: bool = True

    @property
    def is_kid(self) -> bool:
        return self.kind == KID


@dataclass
class Contact:
    id: str
    household_id: str
    name: str
    phone: str | None = None
    relation: str | None = None
    org: str | None = None
    checkin_url: str | None = None
    notes: str | None = None
    is_active: bool = True


@dataclass
class Event:
    id: str
    household_id: str
    title: str
    starts_at_utc: str
    ends_at_utc: str | None = None
    location_name: str | None = None
    location_address: str | None = None
    notes: str | None = None
    bring: str | None = None
    status: str = STATUS_ON
    series_id: str | None = None
    created_by: str | None = None
    created_at: str = ""
    updated_at: str = ""

    @property
    def is_cancelled(self) -> bool:
        return self.status == STATUS_CANCELLED

    @property
    def starts_at(self) -> datetime:
        return datetime.fromisoformat(self.starts_at_utc)


@dataclass
class Casting:
    """One person-or-contact on one event, in one role.

    `who` is the resolved Person or Contact, so callers never have to run a
    second query to find out whether the recipient has a phone number.
    """

    id: str
    event_id: str
    role: str
    who: Person | Contact
    is_household: bool

    @property
    def name(self) -> str:
        return self.who.name

    @property
    def phone(self) -> str | None:
        return self.who.phone

    @property
    def key(self) -> str:
        """Stable identifier used to tick this recipient off a change list."""
        return ("person:" if self.is_household else "contact:") + self.who.id


@dataclass
class Change:
    id: str
    event_id: str
    reason: str
    note: str | None
    made_by: str | None
    made_at: str
    recipients: list[dict[str, Any]] = field(default_factory=list)
    told: dict[str, str] = field(default_factory=dict)


def _person(row: sqlite3.Row) -> Person:
    return Person(
        id=row["id"], household_id=row["household_id"], name=row["name"],
        kind=row["kind"], color=row["color"], initials=row["initials"],
        phone=row["phone"], checkin_url=row["checkin_url"],
        sort_order=row["sort_order"], is_active=bool(row["is_active"]),
    )


def _contact(row: sqlite3.Row) -> Contact:
    return Contact(
        id=row["id"], household_id=row["household_id"], name=row["name"],
        phone=row["phone"], relation=row["relation"], org=row["org"],
        checkin_url=row["checkin_url"], notes=row["notes"],
        is_active=bool(row["is_active"]),
    )


def _event(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"], household_id=row["household_id"], title=row["title"],
        starts_at_utc=row["starts_at_utc"], ends_at_utc=row["ends_at_utc"],
        location_name=row["location_name"], location_address=row["location_address"],
        notes=row["notes"], bring=row["bring"], status=row["status"],
        series_id=row["series_id"], created_by=row["created_by"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


# ---------------------------------------------------------------- household


def create_household(conn, name: str, tz: str = "America/New_York") -> str:
    hid = new_id()
    conn.execute(
        "INSERT INTO households (id, name, timezone, created_at) VALUES (?,?,?,?)",
        (hid, name, tz, _now()),
    )
    conn.commit()
    return hid


def get_household(conn, household_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM households WHERE id = ?", (household_id,)
    ).fetchone()


def only_household(conn) -> sqlite3.Row | None:
    """The single household this deployment serves, or None before setup."""
    return conn.execute(
        "SELECT * FROM households ORDER BY created_at LIMIT 1"
    ).fetchone()


# ---------------------------------------------------------------- people


def add_person(
    conn, household_id: str, name: str, kind: str,
    color: str | None = None, phone: str | None = None,
    checkin_url: str | None = None, initials: str | None = None,
) -> str:
    if kind not in (KID, ADULT):
        raise ValueError(f"kind must be {KID!r} or {ADULT!r}, got {kind!r}")

    used = {p.color for p in list_people(conn, household_id)}
    if color is None:
        color = next((c for c in PALETTE if c not in used), PALETTE[0])

    order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM people WHERE household_id = ?",
        (household_id,),
    ).fetchone()["n"]

    pid = new_id()
    conn.execute(
        "INSERT INTO people (id, household_id, name, kind, color, initials,"
        " phone, checkin_url, sort_order, is_active) VALUES (?,?,?,?,?,?,?,?,?,1)",
        (pid, household_id, name, kind, color,
         initials or name.strip()[:2].upper(), phone, checkin_url, order),
    )
    conn.commit()
    return pid


def list_people(conn, household_id: str, kind: str | None = None) -> list[Person]:
    sql = "SELECT * FROM people WHERE household_id = ? AND is_active = 1"
    params: list[Any] = [household_id]
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    sql += " ORDER BY sort_order, name"
    return [_person(r) for r in conn.execute(sql, params).fetchall()]


def get_person(conn, person_id: str) -> Person | None:
    row = conn.execute("SELECT * FROM people WHERE id = ?", (person_id,)).fetchone()
    return _person(row) if row else None


def update_person(conn, person_id: str, **fields: Any) -> None:
    allowed = {"name", "kind", "color", "initials", "phone", "checkin_url",
               "sort_order", "is_active"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"not writable columns: {sorted(unknown)}")
    if not fields:
        return
    prepared = {k: (int(v) if isinstance(v, bool) else v) for k, v in fields.items()}
    assignments = ", ".join(f"{k} = :{k}" for k in prepared)
    prepared["id"] = person_id
    conn.execute(f"UPDATE people SET {assignments} WHERE id = :id", prepared)
    conn.commit()


# ---------------------------------------------------------------- contacts


def add_contact(
    conn, household_id: str, name: str, phone: str | None = None,
    relation: str | None = None, org: str | None = None,
    checkin_url: str | None = None, notes: str | None = None,
) -> str:
    cid = new_id()
    conn.execute(
        "INSERT INTO contacts (id, household_id, name, phone, relation, org,"
        " checkin_url, notes, is_active) VALUES (?,?,?,?,?,?,?,?,1)",
        (cid, household_id, name, phone, relation, org, checkin_url, notes),
    )
    conn.commit()
    return cid


def list_contacts(conn, household_id: str) -> list[Contact]:
    rows = conn.execute(
        "SELECT * FROM contacts WHERE household_id = ? AND is_active = 1"
        " ORDER BY name",
        (household_id,),
    ).fetchall()
    return [_contact(r) for r in rows]


def get_contact(conn, contact_id: str) -> Contact | None:
    row = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    return _contact(row) if row else None


def update_contact(conn, contact_id: str, **fields: Any) -> None:
    allowed = {"name", "phone", "relation", "org", "checkin_url", "notes",
               "is_active"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"not writable columns: {sorted(unknown)}")
    if not fields:
        return
    prepared = {k: (int(v) if isinstance(v, bool) else v) for k, v in fields.items()}
    assignments = ", ".join(f"{k} = :{k}" for k in prepared)
    prepared["id"] = contact_id
    conn.execute(f"UPDATE contacts SET {assignments} WHERE id = :id", prepared)
    conn.commit()


# ---------------------------------------------------------------- events


def _iso(value: datetime | str | None) -> str | None:
    """Aware UTC datetime or ISO string in; ISO string out. Naive is rejected.

    A naive datetime is the November daylight-saving bug waiting to happen, so
    it raises here rather than being assumed to mean anything in particular.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive datetime rejected — pass an aware UTC datetime")
        return value.astimezone(timezone.utc).isoformat(timespec="seconds")
    return value


def add_event(
    conn, household_id: str, title: str, starts_at_utc: datetime | str,
    ends_at_utc: datetime | str | None = None,
    location_name: str | None = None, location_address: str | None = None,
    notes: str | None = None, bring: str | None = None,
    series_id: str | None = None, created_by: str | None = None,
) -> str:
    eid = new_id()
    now = _now()
    conn.execute(
        "INSERT INTO events (id, household_id, title, starts_at_utc, ends_at_utc,"
        " location_name, location_address, notes, bring, status, series_id,"
        " created_by, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (eid, household_id, title, _iso(starts_at_utc), _iso(ends_at_utc),
         location_name, location_address, notes, bring, STATUS_ON, series_id,
         created_by, now, now),
    )
    conn.commit()
    return eid


def add_series(
    conn, household_id: str, title: str, first_start_local: datetime,
    weeks: int, tz: str, duration: timedelta | None = None, **kwargs: Any,
) -> tuple[str, list[str]]:
    """Materialise a weekly repeat into concrete rows. Returns (series_id, ids).

    Deliberately not an RRULE. Each occurrence is a real row so that one
    Tuesday can be rained off without inventing an exception model.

    The start is a **naive local** wall-clock time, and the weekly step is taken
    in local time before each occurrence is converted to UTC. Adding seven days
    to a UTC instant instead would silently move a 5:30pm practice to 4:30pm
    for the whole of November — see localtime.weekly_occurrences.
    """
    from localtime import weekly_occurrences

    series_id = new_id()
    ids = []
    for start in weekly_occurrences(first_start_local, weeks, tz):
        ids.append(add_event(
            conn, household_id, title, start,
            start + duration if duration else None,
            series_id=series_id, **kwargs,
        ))
    return series_id, ids


WRITABLE = {
    "title", "starts_at_utc", "ends_at_utc", "location_name",
    "location_address", "notes", "bring", "status",
}


def update_event(conn, event_id: str, **fields: Any) -> None:
    """Write named columns. Unknown ones raise rather than vanish."""
    if not fields:
        return
    unknown = set(fields) - WRITABLE
    if unknown:
        raise ValueError(f"not writable columns: {sorted(unknown)}")

    prepared: dict[str, Any] = {
        k: (_iso(v) if isinstance(v, datetime) else v) for k, v in fields.items()
    }
    prepared["updated_at"] = _now()
    assignments = ", ".join(f"{k} = :{k}" for k in prepared)
    prepared["id"] = event_id
    conn.execute(f"UPDATE events SET {assignments} WHERE id = :id", prepared)
    conn.commit()


def get_event(conn, event_id: str) -> Event | None:
    row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    return _event(row) if row else None


def events_between(
    conn, household_id: str, start: datetime, end: datetime,
    person_id: str | None = None,
) -> list[Event]:
    """Events starting in [start, end). Optionally only a given person's.

    Cancelled events are included. A cancellation is information — the week
    view strikes it through rather than hiding it, so nobody turns up.
    """
    window = (
        household_id,
        _iso(start),
        _iso(end),
    )
    if person_id:
        # person_id binds inside the JOIN, which the parser reaches before the
        # WHERE clause — hence the parameter order here.
        rows = conn.execute(
            "SELECT DISTINCT e.* FROM events e"
            " JOIN event_people ep ON ep.event_id = e.id AND ep.person_id = ?"
            " WHERE e.household_id = ? AND e.starts_at_utc >= ?"
            " AND e.starts_at_utc < ? ORDER BY e.starts_at_utc",
            (person_id, *window),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT e.* FROM events e"
            " WHERE e.household_id = ? AND e.starts_at_utc >= ?"
            " AND e.starts_at_utc < ? ORDER BY e.starts_at_utc",
            window,
        ).fetchall()
    return [_event(r) for r in rows]


def delete_series(conn, series_id: str) -> int:
    cursor = conn.execute("DELETE FROM events WHERE series_id = ?", (series_id,))
    conn.commit()
    return cursor.rowcount


# ---------------------------------------------------------------- casting


def cast(
    conn, event_id: str, role: str,
    person_id: str | None = None, contact_id: str | None = None,
) -> str:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; known: {sorted(ROLES)}")
    if (person_id is None) == (contact_id is None):
        raise ValueError("pass exactly one of person_id or contact_id")

    rid = new_id()
    conn.execute(
        "INSERT INTO event_people (id, event_id, person_id, contact_id, role)"
        " VALUES (?,?,?,?,?)",
        (rid, event_id, person_id, contact_id, role),
    )
    conn.commit()
    return rid


def casting(conn, event_id: str) -> list[Casting]:
    """Everyone attached to an event, with their record already resolved."""
    rows = conn.execute(
        "SELECT * FROM event_people WHERE event_id = ?", (event_id,)
    ).fetchall()

    out: list[Casting] = []
    for row in rows:
        if row["person_id"]:
            who: Person | Contact | None = get_person(conn, row["person_id"])
            household = True
        else:
            who = get_contact(conn, row["contact_id"])
            household = False
        if who is None:          # cascade should prevent this; skip rather than crash
            continue
        out.append(Casting(row["id"], event_id, row["role"], who, household))
    return out


def uncast(conn, casting_id: str) -> None:
    conn.execute("DELETE FROM event_people WHERE id = ?", (casting_id,))
    conn.commit()


# ---------------------------------------------------------------- changes


def record_change(
    conn, event_id: str, reason: str, recipients: list[dict[str, Any]],
    note: str | None = None, made_by: str | None = None,
) -> str:
    cid = new_id()
    conn.execute(
        "INSERT INTO changes (id, event_id, reason, note, made_by, made_at,"
        " recipients_json, told_json) VALUES (?,?,?,?,?,?,?,'{}')",
        (cid, event_id, reason, note, made_by, _now(), json.dumps(recipients)),
    )
    conn.commit()
    return cid


def mark_told(conn, change_id: str, recipient_key: str) -> dict[str, str]:
    """Tick one recipient off the list. Returns the updated told map."""
    row = conn.execute(
        "SELECT told_json FROM changes WHERE id = ?", (change_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"no such change: {change_id}")
    told = json.loads(row["told_json"] or "{}")
    told[recipient_key] = _now()
    conn.execute(
        "UPDATE changes SET told_json = ? WHERE id = ?",
        (json.dumps(told), change_id),
    )
    conn.commit()
    return told


def _change(row: sqlite3.Row) -> Change:
    return Change(
        id=row["id"], event_id=row["event_id"], reason=row["reason"],
        note=row["note"], made_by=row["made_by"], made_at=row["made_at"],
        recipients=json.loads(row["recipients_json"] or "[]"),
        told=json.loads(row["told_json"] or "{}"),
    )


def get_change(conn, change_id: str) -> Change | None:
    row = conn.execute("SELECT * FROM changes WHERE id = ?", (change_id,)).fetchone()
    return _change(row) if row else None


def event_changes(conn, event_id: str) -> list[Change]:
    rows = conn.execute(
        "SELECT * FROM changes WHERE event_id = ? ORDER BY made_at DESC",
        (event_id,),
    ).fetchall()
    return [_change(r) for r in rows]


# ---------------------------------------------------------------- self test


def _self_test() -> int:
    import tempfile

    from localtime import to_local

    failures = 0

    def check(label: str, got: Any, expected: Any) -> None:
        nonlocal failures
        ok = got == expected
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {label:<50} {got!r}")

    def expect_error(label: str, action) -> None:
        try:
            action()
        except (ValueError, sqlite3.IntegrityError):
            check(label, True, True)
        else:
            check(label, False, True)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        conn = connect(Path(tmp) / "test.db")
        try:
            check("migrations applied", migrate(conn), len(MIGRATIONS))

            hid = create_household(conn, "Home", "America/New_York")
            check("household is findable", only_household(conn)["name"], "Home")

            ava = add_person(conn, hid, "Ava", KID)
            eli = add_person(conn, hid, "Eli", KID)
            dad = add_person(conn, hid, "Jason", ADULT, phone="+15551110000")
            check("three people", len(list_people(conn, hid)), 3)
            check("two kids", len(list_people(conn, hid, KID)), 2)
            check("colours differ",
                  get_person(conn, ava).color != get_person(conn, eli).color, True)
            check("initials derived", get_person(conn, ava).initials, "AV")
            expect_error("bad kind rejected",
                         lambda: add_person(conn, hid, "X", "dog"))

            sarah = add_contact(conn, hid, "Sarah Chen", "+15552223333", "carpool")
            coach = add_contact(conn, hid, "Coach Miller", "+15554445555", "coach")
            check("two contacts", len(list_contacts(conn, hid)), 2)

            # Tuesday practice at 5:30pm local, run long enough to cross the
            # November clock change — the case that used to move practice.
            series, ids = add_series(
                conn, hid, "Soccer practice", datetime(2026, 9, 8, 17, 30),
                weeks=12, tz="America/New_York",
                duration=timedelta(hours=1, minutes=30),
                location_name="Riverside Park",
                location_address="100 Riverside Dr, Anytown",
            )
            start = datetime.fromisoformat(get_event(conn, ids[0]).starts_at_utc)
            check("series materialised into rows", len(ids), 12)
            check("occurrences share a series id",
                  get_event(conn, ids[3]).series_id, series)
            check("first is 21:30 UTC while EDT is in force", start.hour, 21)
            check("last is 22:30 UTC after the clocks change",
                  datetime.fromisoformat(get_event(conn, ids[11]).starts_at_utc).hour,
                  22)
            check("so every occurrence is still 5:30pm local",
                  {to_local(get_event(conn, i).starts_at_utc,
                            "America/New_York").strftime("%H:%M") for i in ids},
                  {"17:30"})
            check("duration carried to the end time",
                  get_event(conn, ids[0]).ends_at_utc,
                  (start + timedelta(hours=1, minutes=30)).isoformat(timespec="seconds"))

            expect_error("naive datetime rejected", lambda: add_event(
                conn, hid, "Bad", datetime(2026, 9, 8, 17, 30)))

            first = ids[0]
            cast(conn, first, ROLE_ATTENDING, person_id=ava)
            cast(conn, first, ROLE_DRIVING_THERE, person_id=dad)
            cast(conn, first, ROLE_CARPOOL, contact_id=sarah)
            cast(conn, first, ROLE_NOTIFY, contact_id=coach)

            people_on = casting(conn, first)
            check("four on the event", len(people_on), 4)
            check("roles resolve to names",
                  sorted(c.name for c in people_on),
                  ["Ava", "Coach Miller", "Jason", "Sarah Chen"])
            check("household flag distinguishes contacts",
                  sorted(c.name for c in people_on if not c.is_household),
                  ["Coach Miller", "Sarah Chen"])
            check("phone comes back with the casting",
                  next(c.phone for c in people_on if c.name == "Sarah Chen"),
                  "+15552223333")
            check("recipient keys are namespaced",
                  next(c.key for c in people_on if c.name == "Ava"),
                  "person:" + ava)

            expect_error("unknown role rejected",
                         lambda: cast(conn, first, "chauffeur", person_id=dad))
            expect_error("naming both person and contact rejected",
                         lambda: cast(conn, first, ROLE_NOTIFY,
                                      person_id=dad, contact_id=sarah))
            expect_error("naming neither rejected",
                         lambda: cast(conn, first, ROLE_NOTIFY))

            # The week view.
            week_start = datetime(2026, 9, 7, 4, 0, tzinfo=timezone.utc)
            week = events_between(conn, hid, week_start,
                                  week_start + timedelta(days=7))
            check("one practice this week", len(week), 1)
            check("next week has the next one",
                  len(events_between(conn, hid, week_start + timedelta(days=7),
                                     week_start + timedelta(days=14))), 1)
            check("Ava's week", len(events_between(
                conn, hid, week_start, week_start + timedelta(days=7),
                person_id=ava)), 1)
            check("Eli is on nothing", len(events_between(
                conn, hid, week_start, week_start + timedelta(days=7),
                person_id=eli)), 0)

            # A cancellation is information, not a deletion.
            update_event(conn, first, status=STATUS_CANCELLED)
            check("cancelled event still listed",
                  len(events_between(conn, hid, week_start,
                                     week_start + timedelta(days=7))), 1)
            check("and knows it is cancelled",
                  get_event(conn, first).is_cancelled, True)
            expect_error("unknown column rejected",
                         lambda: update_event(conn, first, wetness="high"))

            # The audit trail.
            recipients = [
                {"key": "contact:" + sarah, "name": "Sarah Chen"},
                {"key": "contact:" + coach, "name": "Coach Miller"},
            ]
            change = record_change(conn, first, "event_cancelled", recipients,
                                   note="rained out", made_by="jason")
            check("change recorded", len(event_changes(conn, first)), 1)
            check("recipients survive the round trip",
                  [r["name"] for r in get_change(conn, change).recipients],
                  ["Sarah Chen", "Coach Miller"])
            check("nobody told yet", get_change(conn, change).told, {})
            mark_told(conn, change, "contact:" + sarah)
            told = get_change(conn, change).told
            check("one ticked off", len(told), 1)
            check("and it is the right one", "contact:" + sarah in told, True)

            # Cascade: deleting an event takes its casting and changes with it.
            conn.execute("DELETE FROM events WHERE id = ?", (first,))
            conn.commit()
            check("casting cascaded away", len(casting(conn, first)), 0)
            check("changes cascaded away", len(event_changes(conn, first)), 0)
            check("rest of the series untouched", len(events_between(
                conn, hid, week_start, week_start + timedelta(days=120))), 11)
            check("series delete takes the rest", delete_series(conn, series), 11)
        finally:
            conn.close()

    print()
    print(f"FAILURES: {failures}" if failures else "the schedule behaves")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
