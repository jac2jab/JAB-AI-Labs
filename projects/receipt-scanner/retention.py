"""How long a receipt is kept.

Retention is policy, not perception. The model's job is to report what is on the
receipt — is there a durable good here, and what is it. This file decides what
that means for the archive, so the rule can be read, argued with, and changed in
one place.

The rule, as stated by the owner of the archive:

    No warranty item   ->  2 years from the purchase date
    Warranty item      ->  the warranty term, plus a grace period

The original app got this wrong in a way that mattered. Its cleanup deleted
everything with a purchase date older than two years and never looked at the
warranty flag at all — so the ten-year-warranty receipt, the exact document the
app exists to preserve, was the first thing it would have thrown away.

Run this file directly to check the policy against its examples:

    python retention.py
"""

from datetime import date, timedelta

#: Everything without a warranty item.
DEFAULT_YEARS = 2

#: Kept past the warranty's end, because a claim filed on the last day still
#: needs the receipt afterwards. Set to 0 for retention that ends exactly with
#: the warranty.
GRACE_DAYS = 90

#: Per-category overrides on DEFAULT_YEARS, for categories that need longer than
#: the flat rule. Deliberately empty: the flat two years is the policy today.
#: A deductible-expense category wanting the IRS window would be one line here,
#: e.g. "Business": 7.
CATEGORY_OVERRIDES: dict[str, int] = {}

#: Offered in the review screen's warranty dropdown. Months, or None for items
#: whose warranty does not expire.
WARRANTY_TERMS: list[tuple[str, int | None]] = [
    ("90 days", 3),
    ("6 months", 6),
    ("1 year", 12),
    ("2 years", 24),
    ("3 years", 36),
    ("5 years", 60),
    ("10 years", 120),
    ("Lifetime", None),
]


def add_months(start: date, months: int) -> date:
    """Add whole months, clamping to the last valid day of the target month.

    31 Jan + 1 month is 28 Feb, not an exception. ``timedelta`` cannot do this
    and ``dateutil`` is not worth a dependency for one function.
    """
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def retention_for(
    purchased_on: date,
    has_warranty: bool = False,
    warranty_months: int | None = None,
    category: str | None = None,
) -> tuple[date | None, str]:
    """Decide when this receipt may be deleted.

    Returns ``(retention_until, reason)``. ``retention_until`` of None means
    keep indefinitely — a lifetime warranty. The reason is shown on the review
    and cleanup screens so no deletion is ever unexplained (Principle 2).
    """
    if has_warranty:
        if warranty_months is None:
            return None, "lifetime warranty — kept indefinitely"
        ends = add_months(purchased_on, warranty_months)
        until = ends + timedelta(days=GRACE_DAYS)
        term = _describe_months(warranty_months)
        return until, (
            f"{term} warranty from {purchased_on.isoformat()} ends "
            f"{ends.isoformat()}; kept {GRACE_DAYS} days past that"
        )

    years = CATEGORY_OVERRIDES.get(category or "", DEFAULT_YEARS)
    until = add_months(purchased_on, years * 12)
    if category and category in CATEGORY_OVERRIDES:
        return until, f"{years} years for category {category!r}"
    return until, f"no warranty item — standard {years} years from purchase"


def _describe_months(months: int) -> str:
    if months % 12 == 0:
        years = months // 12
        return f"{years} year" + ("s" if years != 1 else "")
    return f"{months} month" + ("s" if months != 1 else "")


def is_expired(retention_until: date | None, today: date | None = None) -> bool:
    """True when a receipt may be offered for deletion.

    A None retention date is never expired. Cleanup calls this and nothing else,
    so there is no path by which a warranty receipt is offered early.
    """
    if retention_until is None:
        return False
    return retention_until < (today or date.today())


_CASES = [
    # (label, purchased, has_warranty, months, expected retention_until)
    ("coffee, no warranty",
     date(2026, 3, 17), False, None, date(2028, 3, 17)),
    ("Lowe's drill, 10 year warranty",
     date(2026, 3, 17), True, 120, date(2036, 6, 15)),
    ("laptop, 1 year warranty",
     date(2026, 3, 17), True, 12, date(2027, 6, 15)),
    ("cast iron, lifetime warranty",
     date(2026, 3, 17), True, None, None),
    ("leap day purchase, no warranty",
     date(2024, 2, 29), False, None, date(2026, 2, 28)),
    # 31 Jan + 12 months clamps to 31 Jan 2027, then +90 days lands on 1 May.
    ("month-end purchase, 1 year warranty",
     date(2026, 1, 31), True, 12, date(2027, 5, 1)),
]


def _self_test() -> int:
    failures = 0
    print("retention policy")
    print("-" * 72)
    for label, purchased, warranty, months, expected in _CASES:
        until, reason = retention_for(purchased, warranty, months)
        ok = until == expected
        failures += not ok
        shown = until.isoformat() if until else "never"
        print(f"{'ok  ' if ok else 'FAIL'}  {label:<34} {shown:<12} {reason}")

    print()
    print("cleanup eligibility on 2028-06-01")
    print("-" * 72)
    today = date(2028, 6, 1)
    checks = [
        ("coffee bought 2026-03-17", date(2028, 3, 17), True),
        ("drill with 10y warranty", date(2036, 6, 15), False),
        ("lifetime warranty item", None, False),
    ]
    for label, until, expected in checks:
        got = is_expired(until, today)
        ok = got == expected
        failures += not ok
        verdict = "offered for deletion" if got else "kept"
        print(f"{'ok  ' if ok else 'FAIL'}  {label:<34} {verdict}")

    print()
    print(f"FAILURES: {failures}" if failures else "policy holds")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
