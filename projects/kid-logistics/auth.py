"""Local accounts, so the family schedule is not simply readable by the internet.

Lifted almost verbatim from receipt-scanner's auth.py, which had already earned
its keep. Two things changed and both are worth knowing:

**A user belongs to a household.** Today there is one, and the constraint is
close to free. It is here so that "other families could use this" is a feature
to build rather than a migration to survive.

**A user remembers which phone they are on.** iOS and Android disagree about
how to prefill an SMS body (see links.py), and guessing per request from the
User-Agent string is how you end up with an app that works for one parent and
silently fails for the other. Detected once, stored, overridable in settings.

Otherwise unchanged and deliberately small: scrypt from the standard library,
an opaque session token in an HttpOnly cookie, and a table. No JWT, no OAuth,
no third party — there is no identity provider because there is no cloud.

Both parents share one household. Who made a change is recorded on the row;
neither account has a private shelf.

    python auth.py
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

#: scrypt parameters. n=2**15 costs ~100ms per attempt on this class of
#: machine — unnoticeable on a login, expensive in bulk.
SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1
KEY_BYTES = 32

#: scrypt needs 128 * N * r bytes — 32MB at these settings, which is exactly
#: OpenSSL's default ceiling, so it refuses with "memory limit exceeded" unless
#: told otherwise. Derived rather than hardcoded so tuning N above cannot
#: silently break the hash.
SCRYPT_MAXMEM = 128 * SCRYPT_N * SCRYPT_R * 2

#: Long, because re-entering a passcode on a phone every day is how people end
#: up choosing '1111'.
SESSION_DAYS = 90

MIN_PASSCODE_LENGTH = 6

#: Failed attempts before a name is locked out, and for how long. Held in
#: memory: a restart clears it, which is acceptable here and avoids a write on
#: every failed guess.
MAX_ATTEMPTS = 8
LOCKOUT_SECONDS = 300
_attempts: dict[str, list[float]] = {}

#: What links.py needs to know about the phone in your hand.
IOS = "ios"
ANDROID = "android"
PLATFORMS = (IOS, ANDROID)


@dataclass
class User:
    id: str
    household_id: str
    name: str
    created_at: str
    platform: str | None = None
    person_id: str | None = None

    @property
    def key(self) -> str | None:
        """How this account appears in a recipient list, so it can be excluded."""
        return ("person:" + self.person_id) if self.person_id else None


class AuthError(Exception):
    """Something a person should be told about, in words they can act on."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(passcode: str, salt: bytes) -> str:
    return hashlib.scrypt(
        passcode.encode("utf-8"), salt=salt,
        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=KEY_BYTES,
        maxmem=SCRYPT_MAXMEM,
    ).hex()


def _user(row: sqlite3.Row) -> User:
    return User(row["id"], row["household_id"], row["name"],
                row["created_at"], row["platform"], row["person_id"])


def user_count(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM users WHERE is_active = 1"
    ).fetchone()["n"]


def list_users(conn: sqlite3.Connection) -> list[User]:
    rows = conn.execute(
        "SELECT id, household_id, name, created_at, platform, person_id"
        " FROM users WHERE is_active = 1 ORDER BY created_at"
    ).fetchall()
    return [_user(r) for r in rows]


def create_user(
    conn: sqlite3.Connection, household_id: str, name: str, passcode: str,
) -> User:
    name = name.strip()
    if not name:
        raise AuthError("a name is required")
    if len(passcode) < MIN_PASSCODE_LENGTH:
        raise AuthError(
            f"the passcode must be at least {MIN_PASSCODE_LENGTH} characters"
        )

    salt = secrets.token_bytes(16)
    user = User(uuid.uuid4().hex, household_id, name, _now())
    try:
        conn.execute(
            "INSERT INTO users (id, household_id, name, passcode_hash, salt,"
            " platform, created_at, is_active) VALUES (?,?,?,?,?,NULL,?,1)",
            (user.id, household_id, name, _hash(passcode, salt), salt.hex(),
             user.created_at),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise AuthError(f"there is already an account called {name!r}") from None
    return user


def _throttled(name: str) -> int:
    """Seconds remaining on a lockout, or 0."""
    recent = [t for t in _attempts.get(name, []) if time.monotonic() - t < LOCKOUT_SECONDS]
    _attempts[name] = recent
    if len(recent) < MAX_ATTEMPTS:
        return 0
    return int(LOCKOUT_SECONDS - (time.monotonic() - recent[0]))


def verify(conn: sqlite3.Connection, name: str, passcode: str) -> User:
    """Check a passcode. Raises AuthError with something worth reading."""
    name = name.strip()
    wait = _throttled(name)
    if wait:
        raise AuthError(f"too many attempts — try again in {wait // 60 + 1} minutes")

    row = conn.execute(
        "SELECT id, household_id, name, passcode_hash, salt, created_at,"
        " platform, person_id FROM users WHERE name = ? AND is_active = 1",
        (name,),
    ).fetchone()

    # Hash regardless of whether the name exists, so the response time does not
    # reveal which names are real.
    salt = bytes.fromhex(row["salt"]) if row else secrets.token_bytes(16)
    expected = row["passcode_hash"] if row else _hash("", salt)
    candidate = _hash(passcode, salt)

    if row is None or not hmac.compare_digest(candidate, expected):
        _attempts.setdefault(name, []).append(time.monotonic())
        raise AuthError("that name and passcode do not match")

    _attempts.pop(name, None)
    return _user(row)


def link_person(conn: sqlite3.Connection, user_id: str, person_id: str) -> None:
    """Say which household member this account is.

    Without this the app cannot tell that "Jason the driver" and "jason the
    account" are the same human, and will put you on your own list of people
    to text.
    """
    conn.execute("UPDATE users SET person_id = ? WHERE id = ?", (person_id, user_id))
    conn.commit()


def set_platform(conn: sqlite3.Connection, user_id: str, platform: str) -> None:
    """Remember which phone this account uses. See links.py for why."""
    if platform not in PLATFORMS:
        raise AuthError(f"platform must be one of {PLATFORMS}, got {platform!r}")
    conn.execute("UPDATE users SET platform = ? WHERE id = ?", (platform, user_id))
    conn.commit()


def detect_platform(user_agent: str | None) -> str:
    """Best guess from a User-Agent. Stored once, not trusted per request.

    Defaults to Android, whose `?body=` form is the RFC 5724 one — so a wrong
    guess degrades to standards-compliant behaviour rather than Apple's quirk.
    """
    ua = (user_agent or "").lower()
    if any(marker in ua for marker in ("iphone", "ipad", "ipod")):
        return IOS
    # iPadOS 13+ claims to be a Mac; Macs are not phones, but a Mac user
    # texting from Messages wants the iOS form too.
    if "macintosh" in ua and "safari" in ua and "chrome" not in ua:
        return IOS
    return ANDROID


def start_session(conn: sqlite3.Connection, user: User) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at)"
        " VALUES (?, ?, ?, ?)",
        (token, user.id, _now(), expires.isoformat(timespec="seconds")),
    )
    conn.commit()
    return token


def session_user(conn: sqlite3.Connection, token: str | None) -> User | None:
    if not token:
        return None
    row = conn.execute(
        "SELECT u.id, u.household_id, u.name, u.created_at, u.platform,"
        " u.person_id, s.expires_at FROM sessions s"
        " JOIN users u ON u.id = s.user_id"
        " WHERE s.token = ? AND u.is_active = 1",
        (token,),
    ).fetchone()
    if row is None:
        return None
    if row["expires_at"] < _now():
        end_session(conn, token)
        return None
    return _user(row)


def end_session(conn: sqlite3.Connection, token: str | None) -> None:
    if token:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()


def purge_expired_sessions(conn: sqlite3.Connection) -> int:
    cursor = conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_now(),))
    conn.commit()
    return cursor.rowcount


def _self_test() -> int:
    import tempfile
    from pathlib import Path

    import db

    failures = 0

    def check(label: str, got, expected) -> None:
        nonlocal failures
        ok = got == expected
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {label:<52} {got!r}")

    def expect_refusal(label: str, action) -> None:
        """An AuthError is the pass condition here, not the failure."""
        try:
            action()
        except AuthError:
            check(label, True, True)
        else:
            check(label, False, True)

    def expect_refusal_quietly(action) -> None:
        try:
            action()
        except AuthError:
            pass

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        conn = db.connect(Path(tmp) / "auth.db")
        try:
            hid = db.create_household(conn, "Home")
            check("no users on a fresh database", user_count(conn), 0)

            jason = create_user(conn, hid, "jason", "correct-horse")
            check("account created", jason.name, "jason")
            check("account knows its household", jason.household_id, hid)
            check("user count", user_count(conn), 1)

            expect_refusal("duplicate name rejected",
                           lambda: create_user(conn, hid, "jason", "another-one"))
            expect_refusal("short passcode rejected",
                           lambda: create_user(conn, hid, "short", "12345"))
            expect_refusal("wrong passcode rejected",
                           lambda: verify(conn, "jason", "wrong"))
            expect_refusal("unknown name rejected",
                           lambda: verify(conn, "nobody", "whatever"))

            _attempts.clear()
            user = verify(conn, "jason", "correct-horse")
            check("correct passcode accepted", user.id, jason.id)

            # Platform memory.
            check("platform unset to begin with", user.platform, None)
            set_platform(conn, user.id, IOS)
            check("platform remembered", verify(conn, "jason", "correct-horse").platform, IOS)
            expect_refusal("nonsense platform rejected",
                           lambda: set_platform(conn, user.id, "blackberry"))

            # Linking the account to the household member it belongs to.
            check("account is nobody in particular yet", user.key, None)
            me = db.add_person(conn, hid, "Jason", db.ADULT, phone="+15551110000")
            link_person(conn, user.id, me)
            linked = verify(conn, "jason", "correct-horse")
            check("account now knows who it is", linked.person_id, me)
            check("and offers a key a recipient list can exclude",
                  linked.key, "person:" + me)

            check("iPhone UA detected", detect_platform(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
                "AppleWebKit/605.1.15 Version/17.5 Mobile/15E148 Safari/604.1"), IOS)
            check("iPad UA detected", detect_platform(
                "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X)"), IOS)
            check("Pixel UA detected", detect_platform(
                "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                "Chrome/126.0 Mobile Safari/537.36"), ANDROID)
            check("desktop Safari treated as iOS", detect_platform(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 Version/17.5 Safari/605.1.15"), IOS)
            check("unknown UA falls back to the RFC form",
                  detect_platform(None), ANDROID)

            token = start_session(conn, user)
            check("session resolves to the user",
                  session_user(conn, token).name, "jason")
            check("session carries the household",
                  session_user(conn, token).household_id, hid)
            check("garbage token resolves to nobody", session_user(conn, "nope"), None)
            check("no token resolves to nobody", session_user(conn, None), None)

            end_session(conn, token)
            check("signed out session is dead", session_user(conn, token), None)

            # An expired session is refused and cleaned up, not honoured.
            stale = start_session(conn, user)
            conn.execute(
                "UPDATE sessions SET expires_at = ? WHERE token = ?",
                ("2020-01-01T00:00:00+00:00", stale),
            )
            conn.commit()
            check("expired session refused", session_user(conn, stale), None)
            check("and swept up", conn.execute(
                "SELECT COUNT(*) AS n FROM sessions WHERE token = ?",
                (stale,)).fetchone()["n"], 0)

            # The second parent, sharing the one household.
            create_user(conn, hid, "wife", "another-passcode")
            check("two accounts", user_count(conn), 2)
            check("both listed", [u.name for u in list_users(conn)],
                  ["jason", "wife"])
            check("both in the same household",
                  len({u.household_id for u in list_users(conn)}), 1)

            # A correct passcode must not get through during a lockout.
            _attempts.clear()
            for _ in range(MAX_ATTEMPTS):
                expect_refusal_quietly(lambda: verify(conn, "jason", "wrong"))
            try:
                verify(conn, "jason", "correct-horse")
                check("lockout survives a correct passcode", False, True)
            except AuthError as exc:
                check("lockout survives a correct passcode",
                      "too many attempts" in str(exc), True)
        finally:
            _attempts.clear()
            conn.close()

    print()
    print(f"FAILURES: {failures}" if failures else "accounts behave")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
