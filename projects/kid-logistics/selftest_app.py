"""The whole app, driven through its own routes, on a throwaway database.

The module self-tests check that each part is right on its own. This checks
that they are wired together: that setting the household up, adding people,
creating an event, marking a kid sick and ticking the carpool parent off the
list actually works end to end through HTTP, with real forms and a real cookie.

It runs the 6:40am scenario from the README as a browser would:

    set up  ->  add people  ->  add a carpool event
            ->  Ava is sick  ->  am I still driving?  ->  no
            ->  who to tell  ->  Sarah Chen, MUST, ride is off
            ->  tick her off  ->  1 of 2 told

    python selftest_app.py
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

failures = 0


def check(label: str, got, expected) -> None:
    global failures
    ok = got == expected
    failures += not ok
    shown = got if not isinstance(got, str) or len(got) < 60 else got[:57] + "..."
    print(f"{'ok  ' if ok else 'FAIL'}  {label:<54} {shown!r}")


def contains(label: str, haystack: str, needle: str) -> None:
    check(label, needle in haystack, True)


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="kidlog-selftest-")
    os.environ["KIDLOG_DATA"] = tmp
    os.environ["KIDLOG_DEV"] = "1"

    # Imported after the environment is set, so db.DATA_DIR points at the
    # scratch directory and this can never touch the real schedule.
    import db
    check("test database is the scratch one", str(db.DB_PATH).startswith(tmp), True)

    from fastapi.testclient import TestClient

    import app as application

    client = TestClient(application.app, follow_redirects=False)

    # ---------------------------------------------------------------- setup
    r = client.get("/")
    check("signed out is sent to sign in", r.headers.get("location"), "/signin")
    r = client.get("/signin")
    check("with no household, sign in sends you to setup",
          r.headers.get("location"), "/setup")

    r = client.post("/setup", data={
        "household": "Home", "timezone": "America/New_York",
        "name": "jason", "passcode": "correct-horse",
    })
    check("setup redirects into settings", r.headers.get("location"), "/settings")
    check("and sets a session cookie",
          "kidlog_session" in client.cookies, True)

    r = client.get("/setup")
    check("setup cannot be run twice", r.headers.get("location"), "/signin")

    # ---------------------------------------------------------- people
    client.post("/settings/person", data={"name": "Ava", "kind": "kid"})
    client.post("/settings/person", data={"name": "Eli", "kind": "kid"})
    client.post("/settings/contact", data={
        "name": "Sarah Chen", "phone": "(555) 222-3333", "relation": "carpool"})
    client.post("/settings/contact", data={
        "name": "Coach Miller", "phone": "555-444-5555", "relation": "coach"})

    conn = db.connect()
    hid = db.only_household(conn)["id"]
    people = {p.name: p.id for p in db.list_people(conn, hid)}
    contacts = {c.name: c.id for c in db.list_contacts(conn, hid)}
    check("household has three people", len(people), 3)
    check("Jason was created as a person by setup", "Jason" in people, True)
    check("two contacts", len(contacts), 2)

    # Jason needs a number like anyone else, or the app correctly declines to
    # list him as reachable when the other parent asks for a driving swap.
    client.post(f"/settings/person/{people['Jason']}",
                data={"phone": "555-111-0000"})

    # The account knows which person it is, so it stays off its own list.
    import auth
    me = auth.verify(conn, "jason", "correct-horse")
    check("account is linked to a person", me.person_id, people["Jason"])

    r = client.get("/settings")
    contains("settings names the household", r.text, "Home")
    contains("and lists the carpool contact", r.text, "Sarah Chen")

    # ---------------------------------------------------------- the event
    r = client.post("/event/new", data={
        "title": "Soccer practice", "on": "2026-09-08", "at": "17:30",
        "minutes": "90", "repeat_weeks": "8",
        "location_name": "Riverside Park",
        "location_address": "100 Riverside Dr, Anytown",
        "bring": "Shin guards",
        "attending": [f"person:{people['Ava']}"],
        "driving_there": [f"person:{people['Jason']}"],
        "carpool": [f"contact:{contacts['Sarah Chen']}"],
        "notify": [f"contact:{contacts['Coach Miller']}"],
    })
    check("creating an event redirects to it",
          r.headers["location"].startswith("/event/"), True)
    event_id = r.headers["location"].rsplit("/", 1)[1]

    rows = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
    check("eight occurrences materialised", rows, 8)
    check("everyone was cast on each one",
          conn.execute("SELECT COUNT(*) AS n FROM event_people").fetchone()["n"],
          32)

    r = client.get(f"/event/{event_id}")
    contains("the event page names it", r.text, "Soccer practice")
    contains("shows where", r.text, "Riverside Park")
    contains("shows what to bring", r.text, "Shin guards")
    contains("offers a map link", r.text, "maps.apple.com")
    contains("lists the carpool parent", r.text, "Sarah Chen")
    contains("and offers the change button", r.text, "Something changed")

    r = client.get("/?start=2026-09-08")
    contains("the week shows the practice", r.text, "Soccer practice")
    contains("at local 5:30pm, not 21:30 UTC", r.text, "5:30pm")

    # ------------------------------------------------- the 6:40am scenario
    r = client.get(f"/event/{event_id}/change?reason=kid_sick")
    contains("the sick form offers the attending kid", r.text, "Ava")
    check("but not the sibling who is not going", "Eli" in r.text, False)

    # Submitting without answering the driving question must not guess.
    r = client.post(f"/event/{event_id}/change", data={
        "reason": "kid_sick", "sick_person_id": people["Ava"]})
    check("it refuses to guess about the ride", r.status_code, 200)
    contains("and asks instead", r.text, "still driving")

    # Answer it: staying home with her.
    r = client.post(f"/event/{event_id}/change", data={
        "reason": "kid_sick", "sick_person_id": people["Ava"],
        "still_driving": "no", "note": "Sorry for the short notice.",
    })
    check("answering produces a change",
          r.headers["location"].startswith("/change/"), True)
    change_id = r.headers["location"].rsplit("/", 1)[1]

    r = client.get(f"/change/{change_id}")
    contains("the list names the carpool parent", r.text, "Sarah Chen")
    contains("and the coach", r.text, "Coach Miller")
    check("the list is exactly the two outsiders",
          sorted(x["name"] for x in db.get_change(conn, change_id).recipients),
          ["Coach Miller", "Sarah Chen"])
    contains("the carpool parent is a must-tell", r.text, "RIDE IS OFF")
    contains("progress starts at zero", r.text, "0 of 2")
    contains("the drafted text says he cannot drive", r.text, "not able to drive")
    contains("there is a text link", r.text, "sms:+15552223333")
    contains("and a call link", r.text, "tel:+15554445555")

    # Jason's account was set to iOS by the User-Agent of the test client
    # (unknown -> android), so the RFC form is expected here.
    contains("android SMS separator by default", r.text, "sms:+15552223333?body=")

    # Switch the account to an iPhone and the separator must change.
    client.post("/settings/me", data={"platform": "ios"})
    r = client.get(f"/change/{change_id}")
    # &amp; is correct in an HTML attribute; the browser hands Messages a bare &.
    contains("iPhone SMS separator after switching", r.text,
             "sms:+15552223333&amp;body=")
    check("and the android form is gone",
          "sms:+15552223333?body=" in r.text, False)

    # ---------------------------------------------------------- ticking off
    r = client.post(f"/change/{change_id}/told",
                    data={"key": "contact:" + contacts["Sarah Chen"]})
    check("marking told redirects back", r.headers["location"],
          f"/change/{change_id}")
    r = client.get(f"/change/{change_id}")
    contains("progress moves", r.text, "1 of 2")
    contains("and she is marked told", r.text, "told</span>")

    # ------------------------------------------------- the living document
    r = client.get(f"/event/{event_id}")
    contains("the event now shows as changed", r.text, "changed")
    contains("and carries the history", r.text, "Someone is sick")
    contains("naming who is still to tell", r.text, "Coach Miller")

    r = client.get("/?start=2026-09-08")
    contains("the week flags the outstanding change", r.text, "still to tell")

    # ---------------------------------------------------------- cancelling
    r = client.post(f"/event/{event_id}/change",
                    data={"reason": "event_cancelled", "note": "Rained out."})
    cancel_id = r.headers["location"].rsplit("/", 1)[1]
    r = client.get(f"/change/{cancel_id}")
    contains("cancelling reaches the carpool parent", r.text, "Sarah Chen")
    contains("and the coach", r.text, "Coach Miller")
    contains("with the note in the message", r.text, "Rained out.")

    check("the event is now cancelled",
          db.get_event(conn, event_id).status, db.STATUS_CANCELLED)
    r = client.get("/?start=2026-09-08")
    contains("and the week strikes it through rather than hiding it",
             r.text, "Cancelled")
    contains("the event itself is still listed", r.text, "Soccer practice")

    check("the rest of the series is untouched",
          conn.execute("SELECT COUNT(*) AS n FROM events WHERE status = 'on'"
                       ).fetchone()["n"], 7)

    # ---------------------------------------------------------- kid glance
    r = client.get(f"/kid/{people['Ava']}?start=2026-09-08")
    contains("Ava's page lists her practice", r.text, "Soccer practice")
    r = client.get(f"/kid/{people['Eli']}?start=2026-09-08")
    check("Eli's page does not", "Soccer practice" in r.text, False)
    contains("and says so", r.text, "Nothing on for Eli")

    # ---------------------------------------------------- the second parent
    client.post("/settings/person", data={"name": "Kate", "kind": "adult",
                                          "phone": "555-111-0001"})
    people = {p.name: p.id for p in db.list_people(conn, hid)}
    client.post("/settings/user", data={
        "name": "kate", "passcode": "another-passcode",
        "person_id": people["Kate"]})
    check("two accounts now", auth.user_count(conn), 2)

    other = TestClient(application.app, follow_redirects=False)
    r = other.post("/signin", data={"name": "kate", "passcode": "another-passcode"})
    check("the other parent can sign in", r.headers.get("location"), "/")
    r = other.get("/?start=2026-09-08")
    contains("and sees the same schedule", r.text, "Soccer practice")

    # And can't drive now reaches Kate rather than the coach.
    r = other.post(f"/event/{event_id}/change", data={"reason": "cant_drive"})
    swap_id = r.headers["location"].rsplit("/", 1)[1]
    r = other.get(f"/change/{swap_id}")
    check("can't drive reaches the carpool family and the other parent",
          sorted(x["name"] for x in db.get_change(conn, swap_id).recipients),
          ["Jason", "Sarah Chen"])
    check("the coach is spared", "Coach Miller" in r.text, False)

    # ---------------------------------------------------------- sessions
    r = client.post("/signout")
    check("signing out redirects", r.headers.get("location"), "/signin")
    r = client.get("/")
    check("and the schedule is closed again",
          r.headers.get("location"), "/signin")

    r = client.get("/healthz")
    check("health check answers", r.json()["ok"], True)

    conn.close()

    print()
    print(f"FAILURES: {failures}" if failures else "the app behaves end to end")
    print(f"(scratch database: {tmp})")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
