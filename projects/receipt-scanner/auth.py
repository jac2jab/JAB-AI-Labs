"""Local accounts, so the archive is not simply readable by the Wi-Fi.

This app binds to 0.0.0.0 so a phone can reach it. That means everything else on
the network can reach it too, and what it holds is every vendor, date, amount,
and card fragment in the household. A passcode is the difference between a
private archive and a public one.

Deliberately small: scrypt from the standard library, an opaque session token in
an HttpOnly cookie, and a table. No JWT, no OAuth, no third party — there is no
identity provider involved because there is no cloud involved.

Accounts share one library. Who created a receipt is recorded on the row;
neither account has a private shelf.
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
#: memory: a restart clears it, which is acceptable for a LAN app and avoids a
#: write on every failed guess.
MAX_ATTEMPTS = 8
LOCKOUT_SECONDS = 300
_attempts: dict[str, list[float]] = {}


@dataclass
class User:
    id: str
    name: str
    created_at: str


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


def user_count(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM users WHERE is_active = 1"
    ).fetchone()["n"]


def list_users(conn: sqlite3.Connection) -> list[User]:
    rows = conn.execute(
        "SELECT id, name, created_at FROM users WHERE is_active = 1 ORDER BY created_at"
    ).fetchall()
    return [User(r["id"], r["name"], r["created_at"]) for r in rows]


def create_user(conn: sqlite3.Connection, name: str, passcode: str) -> User:
    name = name.strip()
    if not name:
        raise AuthError("a name is required")
    if len(passcode) < MIN_PASSCODE_LENGTH:
        raise AuthError(
            f"the passcode must be at least {MIN_PASSCODE_LENGTH} characters"
        )

    salt = secrets.token_bytes(16)
    user = User(uuid.uuid4().hex, name, _now())
    try:
        conn.execute(
            "INSERT INTO users (id, name, passcode_hash, salt, created_at, is_active)"
            " VALUES (?, ?, ?, ?, ?, 1)",
            (user.id, name, _hash(passcode, salt), salt.hex(), user.created_at),
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
        "SELECT id, name, passcode_hash, salt, created_at FROM users"
        " WHERE name = ? AND is_active = 1",
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
    return User(row["id"], row["name"], row["created_at"])


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
        "SELECT u.id, u.name, u.created_at, s.expires_at FROM sessions s"
        " JOIN users u ON u.id = s.user_id"
        " WHERE s.token = ? AND u.is_active = 1",
        (token,),
    ).fetchone()
    if row is None:
        return None
    if row["expires_at"] < _now():
        end_session(conn, token)
        return None
    return User(row["id"], row["name"], row["created_at"])


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
        print(f"{'ok  ' if ok else 'FAIL'}  {label:<48} {got!r}")

    # ignore_cleanup_errors because Windows will not unlink a SQLite file while
    # any handle remains open, and a failing check should report the failure
    # rather than bury it under an rmtree traceback.
    def expect_refusal(label: str, action) -> None:
        """An AuthError is the pass condition here, not the failure."""
        try:
            action()
        except AuthError:
            check(label, True, True)
        else:
            check(label, False, True)

    def expect_refusal_quietly(action) -> None:
        """Same, without a line of output — for driving the lockout counter."""
        try:
            action()
        except AuthError:
            pass

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        conn = db.connect(Path(tmp) / "auth.db")
        try:
            check("no users on a fresh archive", user_count(conn), 0)

            jason = create_user(conn, "jason", "correct-horse")
            check("account created", jason.name, "jason")
            check("user count", user_count(conn), 1)

            expect_refusal("duplicate name rejected",
                           lambda: create_user(conn, "jason", "another-one"))
            expect_refusal("short passcode rejected",
                           lambda: create_user(conn, "short", "12345"))
            expect_refusal("wrong passcode rejected",
                           lambda: verify(conn, "jason", "wrong"))
            expect_refusal("unknown name rejected",
                           lambda: verify(conn, "nobody", "whatever"))

            _attempts.clear()
            user = verify(conn, "jason", "correct-horse")
            check("correct passcode accepted", user.id, jason.id)

            token = start_session(conn, user)
            check("session resolves to the user",
                  session_user(conn, token).name, "jason")
            check("garbage token resolves to nobody", session_user(conn, "nope"), None)
            check("no token resolves to nobody", session_user(conn, None), None)

            end_session(conn, token)
            check("signed out session is dead", session_user(conn, token), None)

            # A second household account, sharing the one library.
            create_user(conn, "wife", "another-passcode")
            check("two accounts", user_count(conn), 2)
            check("both listed",
                  [u.name for u in list_users(conn)], ["jason", "wife"])

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
