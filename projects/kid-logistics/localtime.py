"""Wall-clock time for humans, UTC for the database, and the seam between them.

The database stores UTC (see db.py). Every screen shows the household's local
time. This module is the only place that conversion happens, so there is one
place to be wrong rather than nine.

**The bug this module exists to prevent.** Soccer practice is at 5:30pm every
Tuesday. Generating a season by adding seven days to a UTC timestamp gives the
right answer until the clocks change in November, and then every remaining
practice is an hour out — 21:30 UTC is 5:30pm in September and 4:30pm in
December. Repeats must be stepped in *local* time and converted to UTC one
occurrence at a time. `weekly_occurrences` does that, and its self-test walks
straight across the boundary.

**On Windows, zoneinfo needs the tzdata package.** Windows ships no IANA
database, so `ZoneInfo("America/New_York")` raises ZoneInfoNotFoundError
without it. It is in requirements.txt for that reason alone.

    python localtime.py
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday",
             "Friday", "Saturday", "Sunday")


def zone(tz: str) -> ZoneInfo:
    return ZoneInfo(tz)


def to_local(when: datetime | str, tz: str) -> datetime:
    """A UTC instant (or its ISO string) as local wall-clock time."""
    if isinstance(when, str):
        when = datetime.fromisoformat(when)
    if when.tzinfo is None:
        raise ValueError("naive datetime rejected — this must be an aware UTC time")
    return when.astimezone(zone(tz))


def local_to_utc(naive_local: datetime, tz: str) -> datetime:
    """A wall-clock time in the household's zone, as a UTC instant.

    Takes a naive datetime deliberately: "5:30pm on 8 September" is what a
    person types, and it means different UTC instants in different zones.
    """
    if naive_local.tzinfo is not None:
        raise ValueError("pass a naive local datetime — the zone comes from tz")
    return naive_local.replace(tzinfo=zone(tz)).astimezone(timezone.utc)


def weekly_occurrences(
    first_local: datetime, weeks: int, tz: str,
) -> list[datetime]:
    """`weeks` UTC instants, one per week, all at the same local wall time.

    The arithmetic is done on the naive local time and each result converted
    separately, so the clocks changing does not move practice.
    """
    if first_local.tzinfo is not None:
        raise ValueError("pass a naive local datetime")
    if weeks < 1:
        raise ValueError("a series needs at least one occurrence")
    return [
        local_to_utc(first_local + timedelta(weeks=n), tz)
        for n in range(weeks)
    ]


def week_bounds(tz: str, anchor: date | None = None) -> tuple[datetime, datetime]:
    """The UTC window covering the local week (Monday 00:00 to Monday 00:00).

    Computed from local midnight rather than by subtracting hours from UTC,
    because the week containing a clock change is 167 or 169 hours long.
    """
    today = anchor or datetime.now(zone(tz)).date()
    monday = today - timedelta(days=today.weekday())
    start = local_to_utc(datetime.combine(monday, time.min), tz)
    end = local_to_utc(datetime.combine(monday + timedelta(days=7), time.min), tz)
    return start, end


def day_bounds(tz: str, day: date) -> tuple[datetime, datetime]:
    start = local_to_utc(datetime.combine(day, time.min), tz)
    end = local_to_utc(datetime.combine(day + timedelta(days=1), time.min), tz)
    return start, end


def fmt_time(when: datetime | str, tz: str) -> str:
    """`5:30pm`. Built by hand because %-I is not portable to Windows."""
    local = to_local(when, tz)
    hour = local.hour % 12 or 12
    suffix = "am" if local.hour < 12 else "pm"
    if local.minute:
        return f"{hour}:{local.minute:02d}{suffix}"
    return f"{hour}{suffix}"


def fmt_day(when: datetime | str, tz: str) -> str:
    """`Tuesday 8 September`."""
    local = to_local(when, tz)
    return f"{DAY_NAMES[local.weekday()]} {local.day} {local.strftime('%B')}"


def fmt_when(when: datetime | str, tz: str, today: date | None = None) -> str:
    """`Tuesday at 5:30pm`, or `today at 5:30pm` when that is clearer.

    This is the string that goes into every drafted text message, so it is
    written the way a person would say it out loud.
    """
    local = to_local(when, tz)
    now = today or datetime.now(zone(tz)).date()
    delta = (local.date() - now).days
    if delta == 0:
        day = "today"
    elif delta == 1:
        day = "tomorrow"
    elif 2 <= delta <= 6:
        day = DAY_NAMES[local.weekday()]
    else:
        day = f"{DAY_NAMES[local.weekday()]} {local.day} {local.strftime('%B')}"
    return f"{day} at {fmt_time(when, tz)}"


def _self_test() -> int:
    failures = 0

    def check(label, got, expected) -> None:
        nonlocal failures
        ok = got == expected
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {label:<54} {got!r}")

    tz = "America/New_York"

    # The bug this module exists to prevent. A Tuesday 5:30pm practice
    # starting in September and running past the November clock change.
    first = datetime(2026, 9, 8, 17, 30)
    season = weekly_occurrences(first, weeks=12, tz=tz)
    check("twelve occurrences", len(season), 12)
    locals_ = [to_local(u, tz) for u in season]
    check("every one is still 5:30pm local",
          {(d.hour, d.minute) for d in locals_}, {(17, 30)})
    check("every one is still a Tuesday", {d.weekday() for d in locals_}, {1})
    check("but the UTC hour shifts across the change",
          len({u.hour for u in season}), 2)
    check("September is UTC 21:30", season[0].hour, 21)
    check("December is UTC 22:30", season[-1].hour, 22)

    # Naive UTC arithmetic would have produced this, which is the bug.
    naive = [season[0] + timedelta(weeks=n) for n in range(12)]
    check("the naive version drifts by an hour",
          len({to_local(u, tz).hour for u in naive}), 2)
    check("and lands on 4:30pm in December",
          to_local(naive[-1], tz).strftime("%H:%M"), "16:30")

    # Round trips.
    check("local to UTC and back",
          to_local(local_to_utc(datetime(2026, 9, 8, 17, 30), tz), tz).strftime("%H:%M"),
          "17:30")
    check("naive input refused",
          isinstance(_error(lambda: to_local(datetime(2026, 1, 1), tz)), ValueError),
          True)
    check("aware input refused where naive is wanted",
          isinstance(_error(lambda: local_to_utc(
              datetime(2026, 1, 1, tzinfo=timezone.utc), tz)), ValueError),
          True)

    # Week bounds, including the long week.
    start, end = week_bounds(tz, date(2026, 9, 9))
    check("week starts Monday local", to_local(start, tz).strftime("%A %H:%M"),
          "Monday 00:00")
    check("and is 168 hours in a normal week",
          int((end - start).total_seconds() // 3600), 168)
    # US DST ends Sunday 1 November 2026 and begins Sunday 8 March 2026, so
    # the weeks beginning 26 October and 2 March are the odd ones out. This is
    # exactly why the bounds are computed from local midnight.
    start, end = week_bounds(tz, date(2026, 10, 26))
    check("the week the clocks go back is 169 hours",
          int((end - start).total_seconds() // 3600), 169)
    start, end = week_bounds(tz, date(2026, 3, 2))
    check("the week they go forward is 167 hours",
          int((end - start).total_seconds() // 3600), 167)

    day_s, day_e = day_bounds(tz, date(2026, 9, 8))
    check("a day is 24 hours", int((day_e - day_s).total_seconds() // 3600), 24)

    # Formatting.
    sep = datetime(2026, 9, 8, 21, 30, tzinfo=timezone.utc)
    check("time", fmt_time(sep, tz), "5:30pm")
    check("on the hour drops the minutes",
          fmt_time(datetime(2026, 9, 8, 23, 0, tzinfo=timezone.utc), tz), "7pm")
    check("morning",
          fmt_time(datetime(2026, 9, 8, 11, 15, tzinfo=timezone.utc), tz), "7:15am")
    check("noon", fmt_time(datetime(2026, 9, 8, 16, 0, tzinfo=timezone.utc), tz),
          "12pm")
    check("midnight", fmt_time(datetime(2026, 9, 8, 4, 0, tzinfo=timezone.utc), tz),
          "12am")
    check("day", fmt_day(sep, tz), "Tuesday 8 September")
    check("when, today", fmt_when(sep, tz, today=date(2026, 9, 8)),
          "today at 5:30pm")
    check("when, tomorrow", fmt_when(sep, tz, today=date(2026, 9, 7)),
          "tomorrow at 5:30pm")
    check("when, this week", fmt_when(sep, tz, today=date(2026, 9, 6)),
          "Tuesday at 5:30pm")
    check("when, further out", fmt_when(sep, tz, today=date(2026, 8, 1)),
          "Tuesday 8 September at 5:30pm")

    print()
    print(f"FAILURES: {failures}" if failures else "local time behaves")
    return 1 if failures else 0


def _error(action):
    try:
        action()
    except Exception as exc:      # noqa: BLE001 - the type is the assertion
        return exc
    return None


if __name__ == "__main__":
    raise SystemExit(_self_test())
