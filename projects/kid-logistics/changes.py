"""Who needs to know, and why. The reason this app exists.

A shared calendar can tell you what was planned. It cannot tell you that
because Ava is home sick and you were the one driving, *another family's kid*
now has no way to get to practice. Working that out at 6:40am, from memory,
while finding two phone numbers in Messages, is the actual problem.

Three rules this module is built on.

**It is code, not a prompt.** The mapping from "what changed" to "who is
affected" is a literal table below. A model asked to do this would be
approximately right, which is the one thing a list of people to contact may not
be — a missed carpool parent is a child standing on a kerb. It also has to run
in a parking lot in the rain in under five seconds.

**Every recipient carries its own reason.** `Recipient.why` is displayed next
to the name. A list you cannot audit is a list you will stop trusting the first
time it surprises you, and then the app is dead.

**Household members without a phone are not recipients.** You will tell the
nine-year-old at breakfast. Padding the list with people you are standing next
to is how a five-name list becomes a nine-name list nobody reads. Outside
contacts with no number *are* listed, flagged — you need to know you cannot
reach the coach, rather than to quietly not reach him.

This module is pure: it takes records and returns records, touches no database
and no clock, and so its self-test is the real test of the product.

    python changes.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Sequence

from db import (
    DRIVING_ROLES,
    ROLE_ATTENDING,
    ROLE_CARPOOL,
    ROLE_DRIVING_HOME,
    ROLE_DRIVING_THERE,
    ROLE_NOTIFY,
    Casting,
    Event,
    Person,
)

# ---------------------------------------------------------------- vocabulary

KID_SICK = "kid_sick"
EVENT_CANCELLED = "event_cancelled"
RUNNING_LATE = "running_late"
CANT_DRIVE = "cant_drive"
LOCATION_CHANGED = "location_changed"
CUSTOM = "custom"

REASONS = (
    KID_SICK,
    EVENT_CANCELLED,
    RUNNING_LATE,
    CANT_DRIVE,
    LOCATION_CHANGED,
    CUSTOM,
)

#: What each reason is called on the button you press.
REASON_LABELS = {
    KID_SICK: "Someone is sick",
    EVENT_CANCELLED: "It's cancelled",
    RUNNING_LATE: "Running late",
    CANT_DRIVE: "I can't drive",
    LOCATION_CHANGED: "It's moved",
    CUSTOM: "Something else",
}

#: MUST means someone is left standing on a kerb if you skip them. FYI means
#: they would like to know. The change screen sorts MUST to the top and will
#: not let you close the list with a MUST unticked without saying so.
MUST = "must"
FYI = "fyi"

_URGENCY_ORDER = {MUST: 0, FYI: 1}


class ChangeError(Exception):
    """The caller asked something that cannot be answered as posed."""


# ---------------------------------------------------------------- records


@dataclass(frozen=True)
class Recipient:
    key: str                     # "person:<id>" / "contact:<id>", ticks off a change
    name: str
    phone: str | None
    roles: tuple[str, ...]
    why: str
    urgency: str
    is_household: bool

    @property
    def reachable(self) -> bool:
        return bool(self.phone)

    def as_dict(self) -> dict:
        """Shape stored in changes.recipients_json."""
        return {
            "key": self.key, "name": self.name, "phone": self.phone,
            "roles": list(self.roles), "why": self.why,
            "urgency": self.urgency, "is_household": self.is_household,
        }


@dataclass(frozen=True)
class Context:
    """Everything a drafted message needs that isn't on the event.

    `when` arrives already localised — this module never touches a timezone,
    which is what keeps it testable without one.
    """

    when: str = ""
    sick_name: str | None = None
    still_driving: bool | None = None
    late_minutes: int | None = None
    new_location: str | None = None
    note: str | None = None
    signature: str | None = None


# ---------------------------------------------------------------- selectors


def _role_is(casting: Iterable[Casting], *roles: str) -> list[Casting]:
    return [c for c in casting if c.role in roles]


def _household_drivers(casting: Iterable[Casting]) -> list[Casting]:
    return [c for c in casting if c.is_household and c.role in DRIVING_ROLES]


def _attending_household(casting: Iterable[Casting]) -> list[Casting]:
    return [c for c in casting if c.is_household and c.role == ROLE_ATTENDING]


def needs_driving_question(
    casting: Sequence[Casting], sick_person_id: str,
) -> bool:
    """Does marking this person sick leave the ride genuinely in doubt?

    Only when all three hold: somebody from this household is driving, another
    family depends on that ride, and the sick person was the household's only
    reason to go. If a sibling is still going the car goes anyway, so there is
    no question worth interrupting anyone with.
    """
    if not _household_drivers(casting):
        return False
    if not _role_is(casting, ROLE_CARPOOL):
        return False
    others = [c for c in _attending_household(casting)
              if c.who.id != sick_person_id]
    return not others


# ---------------------------------------------------------------- the table


class _Bucket:
    """Collects recipients, merging anyone who lands in the list twice.

    The coach who is both `notify` and `driving_home` is one person and gets
    one text, with both reasons shown and the higher urgency kept.
    """

    def __init__(self, exclude: Iterable[str] = ()) -> None:
        self._items: dict[str, Recipient] = {}
        self._exclude = set(exclude)

    def add(self, casting: Casting, why: str, urgency: str) -> None:
        key = casting.key
        if key in self._exclude:
            return
        # You are standing next to them; you are not going to text them.
        if casting.is_household and not casting.phone:
            return

        existing = self._items.get(key)
        if existing is None:
            self._items[key] = Recipient(
                key=key, name=casting.name, phone=casting.phone,
                roles=(casting.role,), why=why, urgency=urgency,
                is_household=casting.is_household,
            )
            return

        roles = existing.roles
        if casting.role not in roles:
            roles = roles + (casting.role,)
        why_combined = existing.why
        if why not in existing.why:
            why_combined = f"{existing.why}; {why}"
        self._items[key] = replace(
            existing, roles=roles, why=why_combined,
            urgency=min(existing.urgency, urgency, key=_URGENCY_ORDER.get),
        )

    def result(self) -> list[Recipient]:
        return sorted(
            self._items.values(),
            key=lambda r: (_URGENCY_ORDER[r.urgency], r.name.lower()),
        )


def affected(
    event: Event,
    casting: Sequence[Casting],
    reason: str,
    *,
    sick_person_id: str | None = None,
    still_driving: bool | None = None,
    household_adults: Sequence[Person] = (),
    exclude: Iterable[str] = (),
) -> list[Recipient]:
    """Who needs telling about this change, and why.

    `exclude` holds recipient keys to drop — in practice the key of whoever is
    making the change, so the app never tells you to text yourself.
    """
    if reason not in REASONS:
        raise ChangeError(f"unknown reason {reason!r}; known: {sorted(REASONS)}")

    bucket = _Bucket(exclude)

    if reason == KID_SICK:
        _kid_sick(bucket, casting, sick_person_id, still_driving)
    elif reason == EVENT_CANCELLED:
        for c in casting:
            bucket.add(c, "on this event", MUST)
    elif reason == RUNNING_LATE:
        for c in _role_is(casting, *DRIVING_ROLES):
            bucket.add(c, "driving this", MUST)
        for c in _role_is(casting, ROLE_CARPOOL):
            bucket.add(c, "waiting on this ride", MUST)
        for c in _role_is(casting, ROLE_NOTIFY):
            bucket.add(c, "expecting you there", FYI)
    elif reason == CANT_DRIVE:
        _cant_drive(bucket, casting, household_adults, exclude)
    elif reason == LOCATION_CHANGED:
        for c in _role_is(casting, *DRIVING_ROLES):
            bucket.add(c, "driving this — needs the new address", MUST)
        for c in _role_is(casting, ROLE_CARPOOL):
            bucket.add(c, "sharing this ride", MUST)
        for c in _attending_household(casting):
            bucket.add(c, "going to this", MUST)
        for c in _role_is(casting, ROLE_NOTIFY):
            bucket.add(c, "involved in this event", FYI)
    elif reason == CUSTOM:
        for c in casting:
            bucket.add(c, "on this event", FYI)

    return bucket.result()


def _kid_sick(
    bucket: _Bucket,
    casting: Sequence[Casting],
    sick_person_id: str | None,
    still_driving: bool | None,
) -> None:
    if not sick_person_id:
        raise ChangeError("say who is sick — kid_sick needs a person")

    sick = next(
        (c for c in _attending_household(casting) if c.who.id == sick_person_id),
        None,
    )
    if sick is None:
        raise ChangeError(
            "that person is not down as attending this event, so there is "
            "nothing to tell anyone about"
        )
    name = sick.name

    # 1. Whoever expects them.
    for c in _role_is(casting, ROLE_NOTIFY):
        bucket.add(c, f"expecting {name}", MUST)

    # 2. The ride — the part people get wrong.
    carpools = _role_is(casting, ROLE_CARPOOL)
    drivers = _household_drivers(casting)
    others_going = [c for c in _attending_household(casting)
                    if c.who.id != sick_person_id]

    if carpools:
        if not drivers:
            # Another family drives. They must not sit outside your house
            # waiting for a child who is in bed.
            for c in carpools:
                bucket.add(c, f"drives {name} — nobody should wait", MUST)
        elif others_going:
            siblings = ", ".join(sorted(c.name for c in others_going))
            for c in carpools:
                bucket.add(c, f"ride still stands, {siblings} is still going", FYI)
        elif still_driving is True:
            for c in carpools:
                bucket.add(c, "ride still stands, you are still driving", FYI)
        elif still_driving is False:
            for c in carpools:
                bucket.add(c, "RIDE IS OFF — they need another way there", MUST)
        else:
            raise ChangeError(
                f"{name} was the only one going from here and you are driving, "
                "so answer whether you are still going before anyone is told"
            )

    # 3. Anyone else from this household who is driving needs to know before
    #    they pick up keys. (Whoever is making the change is excluded already.)
    for c in drivers:
        bucket.add(c, "driving this — plan has changed", MUST)


def _cant_drive(
    bucket: _Bucket,
    casting: Sequence[Casting],
    household_adults: Sequence[Person],
    exclude: Iterable[str],
) -> None:
    # Everyone whose ride depends on you.
    for c in _role_is(casting, ROLE_CARPOOL):
        bucket.add(c, "their kid is in this car", MUST)
    # Anyone else already down to drive part of this.
    for c in _role_is(casting, *DRIVING_ROLES):
        bucket.add(c, "also driving this", MUST)

    # The other parent is the first person you would ask, and is often not
    # cast on the event at all — which is why the full household list is
    # passed in rather than inferred from the casting.
    excluded = set(exclude)
    already = {c.key for c in casting}
    for adult in household_adults:
        key = "person:" + adult.id
        if key in excluded or key in already or not adult.phone:
            continue
        bucket.add(
            Casting(id="", event_id="", role=ROLE_NOTIFY, who=adult,
                    is_household=True),
            "could cover this run", MUST,
        )

    # The coach is deliberately absent. Who drives is not the coach's problem,
    # and a recipient list that includes people who do not need telling is how
    # people stop reading it.


# ---------------------------------------------------------------- drafting


def draft(
    event: Event, reason: str, recipient: Recipient, ctx: Context,
) -> str:
    """The message body, ready for the person to read before they send it.

    Templates, not a model. This runs while you are standing in a car park and
    has to be instant; and a text that goes out under your name should be
    something you wrote. A "reword this" button can call a model later, off
    the critical path.
    """
    what = event.title
    when = f" {ctx.when}" if ctx.when else ""
    tail = f" {ctx.note}" if ctx.note else ""
    sign = f" — {ctx.signature}" if ctx.signature else ""
    carpool = ROLE_CARPOOL in recipient.roles

    if reason == KID_SICK:
        who = ctx.sick_name or "One of the kids"
        if carpool and ctx.still_driving is False:
            body = (
                f"Hi — {who} is home sick, so I'm not able to drive to {what}"
                f"{when}. Sorry for the short notice — you'll need another "
                "plan for the ride."
            )
        elif carpool and ctx.still_driving is True:
            body = (
                f"Hi — {who} is home sick and won't be at {what}{when}, but "
                "I'm still driving, so pickup is unchanged."
            )
        elif carpool:
            body = (
                f"Hi — {who} is home sick and won't need the ride to {what}"
                f"{when}. No need to wait."
            )
        else:
            body = f"Hi — {who} won't make {what}{when}, home sick."
    elif reason == EVENT_CANCELLED:
        body = f"Heads up — {what}{when} is cancelled."
    elif reason == RUNNING_LATE:
        late = f" about {ctx.late_minutes} minutes" if ctx.late_minutes else ""
        body = f"Running{late} late for {what}{when}."
    elif reason == CANT_DRIVE:
        if recipient.is_household:
            body = f"I can't drive to {what}{when} after all — can you take it?"
        else:
            body = (
                f"Hi — I can't drive to {what}{when} after all. Sorry for the "
                "short notice. Are you able to cover it, or should we sort "
                "something else out?"
            )
    elif reason == LOCATION_CHANGED:
        where = ctx.new_location or event.location_name or "a new location"
        body = f"Heads up — {what}{when} has moved to {where}."
    else:
        body = f"About {what}{when}:"

    return (body + tail + sign).strip()


# ---------------------------------------------------------------- self test


def _self_test() -> int:
    failures = 0

    def check(label, got, expected) -> None:
        nonlocal failures
        ok = got == expected
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {label:<54} {got!r}")

    def expect_error(label, action) -> None:
        try:
            action()
        except ChangeError:
            check(label, True, True)
        else:
            check(label, False, True)

    def person(pid, name, phone=None, kind="kid"):
        return Person(id=pid, household_id="H", name=name, kind=kind,
                      color="#000", initials=name[:2].upper(), phone=phone)

    def contact(cid, name, phone="+1555000"):
        from db import Contact
        return Contact(id=cid, household_id="H", name=name, phone=phone)

    def on(role, who, household):
        return Casting(id="c" + who.id, event_id="E", role=role, who=who,
                       is_household=household)

    def names(rs):
        return sorted(r.name for r in rs)

    event = Event(id="E", household_id="H", title="Soccer practice",
                  starts_at_utc="2026-09-08T21:30:00+00:00",
                  location_name="Riverside Park")

    # The 6:40am scenario, exactly as written in the plan.
    ava = person("p1", "Ava")                      # nine, no phone
    eli = person("p2", "Eli")
    dad = person("p3", "Jason", "+15551110000", kind="adult")
    mum = person("p4", "Kate", "+15551110001", kind="adult")
    sarah = contact("c1", "Sarah Chen", "+15552223333")
    coach = contact("c2", "Coach Miller", "+15554445555")

    base = [
        on(ROLE_ATTENDING, ava, True),
        on(ROLE_DRIVING_THERE, dad, True),
        on(ROLE_CARPOOL, sarah, False),
        on(ROLE_NOTIFY, coach, False),
    ]
    me = "person:p3"          # Jason is the one holding the phone

    # --- the question that has to be asked before anyone is told
    check("ride is genuinely in doubt", needs_driving_question(base, "p1"), True)
    expect_error("and it refuses to guess",
                 lambda: affected(event, base, KID_SICK, sick_person_id="p1",
                                  exclude=[me]))

    # --- Ava is sick and Jason is staying home with her. The whole point.
    out = affected(event, base, KID_SICK, sick_person_id="p1",
                   still_driving=False, exclude=[me])
    check("sick + not driving reaches both", names(out),
          ["Coach Miller", "Sarah Chen"])
    check("the carpool parent is a MUST",
          next(r.urgency for r in out if r.name == "Sarah Chen"), MUST)
    check("and is told the ride is off",
          "RIDE IS OFF" in next(r.why for r in out if r.name == "Sarah Chen"), True)
    check("Jason is not told to text himself", me in [r.key for r in out], False)
    check("Ava has no phone and is not on the list",
          "Ava" in names(out), False)

    # --- Same morning, but Jason still drives. Sarah drops to FYI.
    out = affected(event, base, KID_SICK, sick_person_id="p1",
                   still_driving=True, exclude=[me])
    check("sick + still driving still reaches both", names(out),
          ["Coach Miller", "Sarah Chen"])
    check("but the ride is only an FYI",
          next(r.urgency for r in out if r.name == "Sarah Chen"), FYI)
    check("coach is still a MUST",
          next(r.urgency for r in out if r.name == "Coach Miller"), MUST)

    # --- A sibling is also going, so the car goes anyway and nobody is asked.
    with_sibling = base + [on(ROLE_ATTENDING, eli, True)]
    check("no question when a sibling still goes",
          needs_driving_question(with_sibling, "p1"), False)
    out = affected(event, with_sibling, KID_SICK, sick_person_id="p1",
                   exclude=[me])
    check("ride stands on its own",
          next(r.urgency for r in out if r.name == "Sarah Chen"), FYI)
    check("and says why", "Eli is still going"
          in next(r.why for r in out if r.name == "Sarah Chen"), True)

    # --- The mirror case: another family drives, our kid is sick.
    theirs = [
        on(ROLE_ATTENDING, ava, True),
        on(ROLE_CARPOOL, sarah, False),
        on(ROLE_NOTIFY, coach, False),
    ]
    check("no question when we are not driving",
          needs_driving_question(theirs, "p1"), False)
    out = affected(event, theirs, KID_SICK, sick_person_id="p1", exclude=[me])
    check("the driver must not wait outside",
          next(r.urgency for r in out if r.name == "Sarah Chen"), MUST)
    check("and is told not to", "nobody should wait"
          in next(r.why for r in out if r.name == "Sarah Chen"), True)

    # --- Cancellation reaches everyone reachable, once each.
    out = affected(event, base, EVENT_CANCELLED, exclude=[me])
    check("cancelled reaches everyone reachable", names(out),
          ["Coach Miller", "Sarah Chen"])
    both = base + [on(ROLE_DRIVING_HOME, coach, False)]
    out = affected(event, both, EVENT_CANCELLED, exclude=[me])
    check("two roles, still one person", len(out), 2)
    check("with both roles recorded",
          sorted(next(r.roles for r in out if r.name == "Coach Miller")),
          [ROLE_DRIVING_HOME, ROLE_NOTIFY])

    # --- Can't drive: the coach does not care who is behind the wheel.
    out = affected(event, base, CANT_DRIVE, household_adults=[dad, mum],
                   exclude=[me])
    check("can't drive asks the carpool and the other parent", names(out),
          ["Kate", "Sarah Chen"])
    check("the coach is deliberately spared",
          "Coach Miller" in names(out), False)

    # --- Running late does not wake the coach up as a MUST.
    out = affected(event, base, RUNNING_LATE, exclude=[me])
    check("late reaches the carpool as MUST",
          next(r.urgency for r in out if r.name == "Sarah Chen"), MUST)
    check("and the coach only as FYI",
          next(r.urgency for r in out if r.name == "Coach Miller"), FYI)

    # --- An unreachable contact is listed, flagged, not silently dropped.
    no_number = base + [on(ROLE_NOTIFY, contact("c3", "New Coach", None), False)]
    out = affected(event, no_number, EVENT_CANCELLED, exclude=[me])
    check("contact with no number is still listed",
          "New Coach" in names(out), True)
    check("and is marked unreachable",
          next(r.reachable for r in out if r.name == "New Coach"), False)

    # --- Guard rails.
    expect_error("unknown reason rejected",
                 lambda: affected(event, base, "vibes"))
    expect_error("kid_sick needs a person",
                 lambda: affected(event, base, KID_SICK))
    expect_error("and the person must be going",
                 lambda: affected(event, base, KID_SICK, sick_person_id="p2"))

    # --- Drafts.
    ctx = Context(when="Tuesday at 5:30pm", sick_name="Ava",
                  still_driving=False, signature="Jason")
    out = affected(event, base, KID_SICK, sick_person_id="p1",
                   still_driving=False, exclude=[me])
    to_sarah = next(r for r in out if r.name == "Sarah Chen")
    to_coach = next(r for r in out if r.name == "Coach Miller")
    check("carpool draft says the ride is off",
          "not able to drive" in draft(event, KID_SICK, to_sarah, ctx), True)
    check("coach draft does not mention driving",
          "drive" in draft(event, KID_SICK, to_coach, ctx), False)
    check("coach draft names the event",
          "Soccer practice" in draft(event, KID_SICK, to_coach, ctx), True)
    check("draft is signed",
          draft(event, KID_SICK, to_coach, ctx).endswith("— Jason"), True)

    ctx_late = Context(when="Tuesday at 5:30pm", late_minutes=15)
    out = affected(event, base, RUNNING_LATE, exclude=[me])
    check("late draft carries the number",
          "about 15 minutes late" in draft(
              event, RUNNING_LATE, out[0], ctx_late), True)

    print()
    print(f"FAILURES: {failures}" if failures else "the recipient list behaves")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
