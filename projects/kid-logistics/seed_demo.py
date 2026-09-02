"""A week of made-up family logistics, so the change screen can be tried at once.

This exists to make the app demonstrable in thirty seconds rather than after
twenty minutes of typing. It is **not** a substitute for entering a real week:
the repo's own lesson is that six real newsletters found four bugs no fixture
would have, and the same will be true here. Real carpool arrangements are
messier than anything invented at a keyboard.

It refuses to run against a database that already holds a household, so it can
never overwrite a real schedule.

    KIDLOG_DATA=./data-demo python seed_demo.py
    KIDLOG_DATA=./data-demo KIDLOG_DEV=1 python -m uvicorn app:app --port 8000

Sign in as jason / correct-horse.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, time, timedelta

import auth
import db
import localtime as lt

TZ = "America/New_York"
PASSCODE = "correct-horse"


def next_weekday(start: date, weekday: int) -> date:
    """The next given weekday on or after `start`. Monday is 0."""
    return start + timedelta(days=(weekday - start.weekday()) % 7)


def main() -> int:
    conn = db.connect()
    if db.only_household(conn) is not None:
        print("This database already has a household in it. Refusing to touch it.")
        print(f"Database: {db.DB_PATH}")
        print("Set KIDLOG_DATA to an empty directory to seed a demo elsewhere.")
        return 1

    household = db.create_household(conn, "Demo Household", TZ)

    jason = db.add_person(conn, household, "Jason", db.ADULT, phone="555-111-0000")
    kate = db.add_person(conn, household, "Kate", db.ADULT, phone="555-111-0001")
    ava = db.add_person(conn, household, "Ava", db.KID)
    eli = db.add_person(conn, household, "Eli", db.KID)
    mia = db.add_person(conn, household, "Mia", db.KID, phone="555-111-0004",
                        checkin_url="https://life360.com/")

    user = auth.create_user(conn, household, "jason", PASSCODE)
    auth.link_person(conn, user.id, jason)
    auth.set_platform(conn, user.id, auth.IOS)

    second = auth.create_user(conn, household, "kate", PASSCODE)
    auth.link_person(conn, second.id, kate)
    auth.set_platform(conn, second.id, auth.ANDROID)

    sarah = db.add_contact(conn, household, "Sarah Chen", "555-222-3333",
                           "carpool", org="Ava's soccer")
    marcus = db.add_contact(conn, household, "Marcus Webb", "555-222-4444",
                            "carpool", org="Eli's swim")
    coach = db.add_contact(conn, household, "Coach Miller", "555-444-5555",
                           "coach", org="Riverside FC")
    swim = db.add_contact(conn, household, "Coach Diaz", "555-444-6666",
                          "coach", org="Aquatics Club")
    piano = db.add_contact(conn, household, "Mrs Alvarez", "555-444-7777",
                           "teacher", org="Piano")

    monday = date.today() - timedelta(days=date.today().weekday())

    def at(weekday: int, hh: int, mm: int) -> datetime:
        return datetime.combine(next_weekday(monday, weekday), time(hh, mm))

    made = []

    # Ava's soccer — the carpool that the whole app is really about.
    _, ids = db.add_series(
        conn, household, "Soccer practice", at(1, 17, 30), 8, TZ,
        duration=timedelta(minutes=90),
        location_name="Riverside Park",
        location_address="100 Riverside Dr, Anytown",
        bring="Shin guards, water bottle", created_by="jason")
    for eid in ids:
        db.cast(conn, eid, db.ROLE_ATTENDING, person_id=ava)
        db.cast(conn, eid, db.ROLE_DRIVING_THERE, person_id=jason)
        db.cast(conn, eid, db.ROLE_CARPOOL, contact_id=sarah)
        db.cast(conn, eid, db.ROLE_NOTIFY, contact_id=coach)
    made.append(("Soccer practice", len(ids)))

    # Eli's swim — the other family drives, which routes differently.
    _, ids = db.add_series(
        conn, household, "Swim training", at(3, 6, 45), 8, TZ,
        duration=timedelta(minutes=75),
        location_name="Aquatics Centre",
        location_address="45 Pool Rd, Anytown",
        bring="Goggles, towel", created_by="jason")
    for eid in ids:
        db.cast(conn, eid, db.ROLE_ATTENDING, person_id=eli)
        db.cast(conn, eid, db.ROLE_DRIVING_THERE, contact_id=marcus)
        db.cast(conn, eid, db.ROLE_CARPOOL, contact_id=marcus)
        db.cast(conn, eid, db.ROLE_NOTIFY, contact_id=swim)
    made.append(("Swim training", len(ids)))

    # Piano — no carpool at all, so a change reaches exactly one person.
    _, ids = db.add_series(
        conn, household, "Piano lesson", at(2, 16, 0), 8, TZ,
        duration=timedelta(minutes=45),
        location_name="Mrs Alvarez's",
        location_address="12 Cedar Ave, Anytown", created_by="jason")
    for eid in ids:
        db.cast(conn, eid, db.ROLE_ATTENDING, person_id=mia)
        db.cast(conn, eid, db.ROLE_DRIVING_THERE, person_id=kate)
        db.cast(conn, eid, db.ROLE_NOTIFY, contact_id=piano)
    made.append(("Piano lesson", len(ids)))

    # Saturday match — both parents, both carpools, everybody involved.
    match = db.add_event(
        conn, household, "Soccer match vs Eastside",
        lt.local_to_utc(at(5, 10, 0), TZ),
        location_name="Eastside Fields",
        location_address="900 East Rd, Anytown",
        bring="Full kit, snacks", notes="Arrive 30 minutes early to warm up.",
        created_by="jason")
    db.cast(conn, match, db.ROLE_ATTENDING, person_id=ava)
    db.cast(conn, match, db.ROLE_DRIVING_THERE, person_id=jason)
    db.cast(conn, match, db.ROLE_DRIVING_HOME, person_id=kate)
    db.cast(conn, match, db.ROLE_CARPOOL, contact_id=sarah)
    db.cast(conn, match, db.ROLE_NOTIFY, contact_id=coach)
    made.append(("Soccer match vs Eastside", 1))

    conn.close()

    print(f"Seeded {db.DB_PATH}")
    for title, count in made:
        print(f"  {count:>2}x  {title}")
    print()
    print("Sign in as  jason / correct-horse   (iPhone links)")
    print("        or  kate  / correct-horse   (Android links)")
    print()
    print("The drill worth running first:")
    print("  1. Open the next soccer practice.")
    print("  2. Something changed -> Someone is sick -> Ava.")
    print("  3. It should stop and ask whether you are still driving.")
    print("  4. Answer 'staying home'. Sarah Chen must be a MUST with the ride")
    print("     off; Coach Miller a separate must-tell; nobody else listed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
