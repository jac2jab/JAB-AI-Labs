"""Interpreting the amounts on a receipt.

A vision model can read handwriting. It cannot be trusted to *interpret* it
consistently, because the conventions are local and the model re-decides them on
every call. On a restaurant slip:

    TIP   10-        means ten dollars, zero cents
    TIP   -          means no tip was added to the card
    TIP   CASH       means the tip was left in cash; nothing was charged
    TIP   (blank)    means nothing was written

So the model is asked for one thing only: the characters that are physically in
the box, verbatim. Everything below decides what those characters mean, in code,
where the rule can be read and changed.

This is the same lesson the SE Demo Generator learned four times over: enforce in
code what you would otherwise ask a model to do.

Run this file directly to check the rules against their examples:

    python amounts.py
"""

from decimal import Decimal, InvalidOperation
import re

CENT = Decimal("0.01")

#: What someone writes in a tip box to mean "no tip on this card".
#: Compared after _clean(), so entries are lowercase with single spaces.
NO_TIP_MARKERS = {
    "", "-", "--", "---", "—", "–", "/", "x", "xx",
    "0", "00", "n/a", "na", "none", "nil", "no tip",
    "cash", "cash tip", "tip in cash", "paid cash", "left cash",
}

#: A number finished with a dash instead of cents: ``10-``, ``10 -``, ``10.-``
_TRAILING_DASH = re.compile(r"^(\d[\d,]*)\s*\.?\s*[-–—]+$")

#: Cents written beside the dollars as a fraction: ``10 00/100``
_FRACTION_CENTS = re.compile(r"^(\d[\d,]*)\s+(\d{2})\s*/\s*100$")

#: Currency symbols and non-breaking spaces, removed outright.
_CURRENCY_NOISE = re.compile(r"[$   ]")

#: Runs of ordinary whitespace, collapsed to one space rather than deleted.
_WHITESPACE_RUN = re.compile(r"\s+")


def _clean(raw: str | None) -> str:
    """Lowercase, drop currency symbols, collapse whitespace to single spaces.

    Internal spaces are *kept*: they are what separates ``cash tip`` from
    ``cashtip``, and the dollars from the cents in ``10 00/100``. Each rule
    below strips the spaces it does not want. Deleting them here instead was
    the first version, and it silently broke both of those cases.
    """
    if raw is None:
        return ""
    text = _CURRENCY_NOISE.sub("", str(raw))
    return _WHITESPACE_RUN.sub(" ", text).strip().lower()


def interpret_money(raw: str | None) -> tuple[Decimal | None, str]:
    """Read a written money amount.

    Returns ``(value, note)``. ``value`` is None when the characters do not
    resolve to an amount; ``note`` always explains the decision so the review
    screen can show its work, per MAIOS Principle 2.
    """
    if raw is None or str(raw).strip() == "":
        return None, "nothing written"

    text = _clean(raw)
    original = str(raw).strip()

    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()

    m = _TRAILING_DASH.match(text)
    if m:
        value = _to_decimal(m.group(1))
        if value is None:
            return None, f"could not read {original!r}"
        return _sign(value, negative), f"{original!r} — trailing dash read as .00"

    m = _FRACTION_CENTS.match(text)
    if m:
        dollars = _to_decimal(m.group(1))
        if dollars is None:
            return None, f"could not read {original!r}"
        value = dollars + Decimal(m.group(2)) / 100
        return _sign(value, negative), f"{original!r} — cents written as a fraction"

    value = _to_decimal(text)
    if value is None:
        return None, f"could not read {original!r} as an amount"
    return _sign(value, negative), f"read {original!r}"


def interpret_tip(raw: str | None) -> tuple[Decimal | None, str]:
    """Read a tip box, where an empty-looking box is a real answer.

    A blank, a dash, or the word CASH all mean the same thing to the card
    charge: zero. That is different from an unreadable box, which returns None
    and gets flagged for review.
    """
    text = _clean(raw)

    if text in NO_TIP_MARKERS:
        if raw is None or str(raw).strip() == "":
            return Decimal("0.00"), "tip box empty — no tip charged"
        return Decimal("0.00"), f"{str(raw).strip()!r} — no tip charged to the card"

    return interpret_money(raw)


def _to_decimal(text: str) -> Decimal | None:
    text = text.replace(",", "").replace(" ", "")
    if not text or text == "." or not re.fullmatch(r"\d*\.?\d*", text):
        return None
    try:
        return Decimal(text).quantize(CENT)
    except (InvalidOperation, ValueError):
        return None


def _sign(value: Decimal, negative: bool) -> Decimal:
    return (-value if negative else value).quantize(CENT)


def reconcile(
    subtotal: Decimal | None,
    tax: Decimal | None,
    tip: Decimal | None,
    total: Decimal | None,
    tolerance: Decimal = Decimal("0.02"),
    tip_applicable: bool = True,
) -> tuple[dict[str, Decimal | None], list[str]]:
    """Check the amounts against each other, and derive one if it is missing.

    Arithmetic is the control on the handwriting. A model that reads ``10-`` as
    ``100`` produces a sum that does not close, and gets caught here rather than
    at tax time.

    ``tip_applicable`` distinguishes "this receipt has no tip line" from "the
    tip line couldn't be read." A gas or grocery receipt is the first case, and
    passing ``tip_applicable=False`` for one means: never invent a tip to
    explain a gap, never blame a tip line that does not exist, and when
    subtotal + tax does not reach total, say so without mentioning tip at all
    — on a receipt structurally incapable of having one, the mismatch can only
    be in subtotal, tax, or total.

    Returns the amounts (possibly with one derived) and a list of human-readable
    problems. An empty list means the receipt adds up.
    """
    amounts = {"subtotal": subtotal, "tax": tax, "tip": tip, "total": total}
    problems: list[str] = []

    known = sum(1 for v in (subtotal, tax, tip, total) if v is not None)
    if total is None and subtotal is None:
        problems.append("neither subtotal nor total could be read")
        return amounts, problems

    # Derive a single missing piece rather than flagging it. An illegible tip
    # box on an otherwise legible receipt is arithmetic, not guesswork — but
    # only when a tip is possible at all. A gas receipt with a short subtotal
    # is missing a tax line, not a phantom tip.
    if total is not None and subtotal is not None:
        if tip_applicable and tip is None and tax is not None:
            derived = (total - subtotal - tax).quantize(CENT)
            if derived >= 0:
                amounts["tip"] = tip = derived
                problems.append(
                    f"tip not readable; derived {derived} from total - subtotal - tax"
                )
        elif tax is None and tip is not None:
            derived = (total - subtotal - tip).quantize(CENT)
            if derived >= 0:
                amounts["tax"] = tax = derived

    if total is not None and subtotal is not None:
        computed = subtotal + (tax or Decimal("0.00")) + (tip or Decimal("0.00"))
        gap = (computed - total).quantize(CENT)
        if abs(gap) > tolerance:
            if tip_applicable:
                problems.append(
                    f"amounts do not add up: subtotal {subtotal} + tax "
                    f"{tax or 0} + tip {tip or 0} = {computed}, but total "
                    f"reads {total} (off by {gap})"
                )
            else:
                problems.append(
                    f"amounts do not add up: subtotal {subtotal} + tax "
                    f"{tax or 0} = {computed}, but total reads {total} "
                    f"(off by {gap}) — no tip line on this receipt, so the "
                    f"mismatch is in subtotal, tax, or total"
                )

    if total is not None and total < 0:
        problems.append(f"total is negative ({total}) — a refund, or a misread")

    if tip_applicable and tip is not None and total is not None and total > 0 and tip > total:
        problems.append(f"tip {tip} is larger than the total {total}")

    if known < 2:
        problems.append("only one amount could be read; nothing to check it against")

    return amounts, problems


_TIP_CASES = [
    ("10-", Decimal("10.00")),
    ("10 —", Decimal("10.00")),
    ("10.-", Decimal("10.00")),
    ("$10-", Decimal("10.00")),
    ("-", Decimal("0.00")),
    ("—", Decimal("0.00")),
    ("CASH", Decimal("0.00")),
    ("cash tip", Decimal("0.00")),
    ("X", Decimal("0.00")),
    ("", Decimal("0.00")),
    (None, Decimal("0.00")),
    ("0.00", Decimal("0.00")),
    ("3.50", Decimal("3.50")),
    ("$12.00", Decimal("12.00")),
    ("1,234.56", Decimal("1234.56")),
    ("10 00/100", Decimal("10.00")),
    ("scribble", None),
]

_RECONCILE_CASES = [
    ("restaurant, tip written as 10-",
     (Decimal("42.00"), Decimal("3.36"), Decimal("10.00"), Decimal("55.36")), 0),
    # Caught twice over: the sum does not close, and the tip exceeds the total.
    # Either flag alone would be enough to stop the save.
    ("model misread 10- as 100",
     (Decimal("42.00"), Decimal("3.36"), Decimal("100.00"), Decimal("55.36")), 2),
    ("illegible tip, derived from the other three",
     (Decimal("42.00"), Decimal("3.36"), None, Decimal("55.36")), 1),
    ("big box, no tip line",
     (Decimal("29.31"), Decimal("2.21"), Decimal("0.00"), Decimal("31.52")), 0),
]

_NO_TIP_LINE_CASES = [
    ("gas receipt, clean", (Decimal("41.01"), None, Decimal("41.01")), 0),
    # subtotal + tax genuinely doesn't reach total. On a receipt with no tip
    # line this must be blamed on subtotal/tax/total, never on a phantom tip.
    ("misread total, no tip line to blame it on",
     (Decimal("29.31"), Decimal("2.21"), Decimal("35.95")), 1, "no tip line"),
    # A gap this large, with tip_applicable=False, must never be
    # "recovered" by inventing a tip out of the arithmetic.
    ("large gap is never absorbed into an invented tip",
     (Decimal("16.68"), None, Decimal("16.57")), 1, "no tip line"),
]


def _self_test() -> int:
    failures = 0
    print("tip box interpretation")
    print("-" * 66)
    for raw, expected in _TIP_CASES:
        value, note = interpret_tip(raw)
        ok = value == expected
        failures += not ok
        shown = "(empty)" if raw in (None, "") else repr(raw)
        print(f"{'ok  ' if ok else 'FAIL'}  {shown:<14} -> {str(value):<8}  {note}")

    print()
    print("reconciliation")
    print("-" * 66)
    for label, (sub, tax, tip, total), expected_problems in _RECONCILE_CASES:
        _, problems = reconcile(sub, tax, tip, total)
        ok = len(problems) == expected_problems
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {label}")
        for p in problems:
            print(f"        {p}")

    print()
    print("reconciliation — no tip line at all (tip_applicable=False)")
    print("-" * 66)
    for label, (sub, tax, total), expected_problems, *rest in _NO_TIP_LINE_CASES:
        amounts_out, problems = reconcile(
            sub, tax, Decimal("0.00"), total, tip_applicable=False
        )
        ok = len(problems) == expected_problems
        # A gap must never be laundered into an invented tip when there is no
        # tip line to have produced one.
        ok = ok and amounts_out["tip"] == Decimal("0.00")
        if rest:
            ok = ok and all("tip" not in p or rest[0] in p for p in problems)
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {label}")
        for p in problems:
            print(f"        {p}")

    print()
    print(f"FAILURES: {failures}" if failures else "all rules hold")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
