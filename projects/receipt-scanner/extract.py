"""Reading a receipt photograph with Claude.

The division of labour here is the whole design:

    the model    reports what is physically printed or written on the paper,
                 verbatim, field by field
    this file    decides what those characters mean, checks the amounts against
                 each other, and refuses to pass on anything it cannot verify

Every money field comes back as a *string* — ``total_raw``, ``tip_raw`` — not a
number. Asking a model for a number invites it to normalise, compute, and
quietly fix things; asking it for the characters in the box keeps the
interpretation in amounts.py where the rule is visible. The SE Demo Generator
learned the same lesson four separate times: enforce in code what you would
otherwise ask a model to do.

Run it on a photograph before any web app exists:

    python extract.py samples/lowes.jpg
    python extract.py samples/*.jpg --compare
"""

from __future__ import annotations

import argparse
import base64
import glob
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

import anthropic
import pydantic
from pydantic import BaseModel, Field

import amounts
import images

DEFAULT_MODEL = os.environ.get("RECEIPT_MODEL", "claude-opus-5")

#: Input / output USD per million tokens, for the per-receipt cost line.
#: Sonnet 5 carries introductory pricing through 2026-08-31; the standard rate
#: is used here so the reported figure is never an under-estimate.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

#: A closed set, so the library can be filtered and searched on it. Free-text
#: categories from a model drift ("Home Improvement", "home improvement",
#: "Hardware") and make the column useless.
Category = Literal[
    "Groceries", "Restaurant", "Home Improvement", "Electronics", "Clothing",
    "Auto", "Fuel", "Pharmacy", "Medical", "Travel", "Lodging", "Entertainment",
    "Office Supplies", "Home Goods", "Pet", "Services", "Utilities", "Other",
]

CATEGORIES: tuple[str, ...] = Category.__args__  # type: ignore[attr-defined]


class LineItem(BaseModel):
    description: str = Field(description="The item name as printed on the receipt.")
    amount_raw: str | None = Field(
        default=None, description="The line's price, exactly as printed."
    )


class ReceiptFields(BaseModel):
    """What the model reports seeing. Nothing here is trusted as a number."""

    vendor: str | None = Field(
        default=None,
        description="Business name as printed at the top. Not the address or slogan.",
    )
    purchased_on: str | None = Field(
        default=None,
        description=(
            "The transaction date as YYYY-MM-DD. US receipts print MM/DD/YY. "
            "Null if no date is visible."
        ),
    )
    purchased_on_raw: str | None = Field(
        default=None, description="The date exactly as printed, before conversion."
    )
    subtotal_raw: str | None = Field(
        default=None, description="Subtotal, exactly as printed. Null if absent."
    )
    tax_raw: str | None = Field(
        default=None, description="Tax, exactly as printed. Null if absent."
    )
    tip_raw: str | None = Field(
        default=None,
        description=(
            "The tip box, transcribed EXACTLY as it appears including any "
            "handwriting. If it holds '10-' return '10-'. If it holds a single "
            "dash return '-'. If it says CASH return 'CASH'. If the box is "
            "printed but empty return an empty string. If there is no tip line "
            "at all return null. Never convert, never compute, never infer."
        ),
    )
    total_raw: str | None = Field(
        default=None,
        description=(
            "The final amount charged, exactly as printed or written. On a "
            "restaurant slip this is the handwritten TOTAL line, not the "
            "printed amount above it."
        ),
    )
    card_last4: str | None = Field(
        default=None,
        description=(
            "ONLY the last four digits of the card, as printed after the "
            "masking characters. Never return a full card number. Null if the "
            "payment was cash or no digits are shown."
        ),
    )
    payment_method: str | None = Field(
        default=None, description="e.g. VISA, MASTERCARD, AMEX, DEBIT, CASH."
    )
    category: Category = Field(
        description="Best fit for what was bought. Use 'Other' if unclear."
    )
    items: list[LineItem] = Field(
        default_factory=list,
        description="Line items, if legible. An empty list is fine.",
    )
    has_durable_goods: bool = Field(
        description=(
            "True if the receipt includes a physical product that plausibly "
            "carries a manufacturer warranty — tools, appliances, electronics, "
            "furniture, sporting goods. False for food, drink, fuel, "
            "consumables, and services."
        )
    )
    durable_goods_note: str | None = Field(
        default=None,
        description="Which item, if has_durable_goods is true. Null otherwise.",
    )
    handwritten_amounts: bool = Field(
        description="True if the tip or total was filled in by hand."
    )
    uncertain_fields: list[str] = Field(
        default_factory=list,
        description=(
            "Names of fields above you could not read confidently — e.g. "
            "['tip_raw', 'card_last4']. Report doubt rather than guessing."
        ),
    )
    transcript: str = Field(
        description="Full plain-text transcription of the receipt, top to bottom."
    )


SYSTEM_PROMPT = """\
You transcribe receipts. You are the eyes of an archive, not its accountant.

Report what is physically on the paper. Do not normalise, do not compute, do not
correct, and do not fill a gap with what would be reasonable. Every field ending
in _raw must contain the characters as they appear, including handwriting,
dashes, and currency symbols. Downstream code interprets them.

Restaurant slips are the hard case. The printed amount is the pre-tip charge;
the handwritten TOTAL below it is what was actually charged. Report both — the
printed one as subtotal_raw or the amount it is labelled, the handwritten one as
total_raw. Transcribe the tip box exactly, whatever is in it.

If something is illegible, say so in uncertain_fields rather than guessing. A
reported doubt costs one glance at the review screen. A confident wrong number
costs a wrong tax return.

Never output a full payment card number. Only the last four digits."""


@dataclass
class Extraction:
    """The result of reading one photograph."""

    fields: ReceiptFields
    amounts: dict[str, Decimal | None]
    notes: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    purchased_on: date | None = None
    card_last4: str | None = None
    model: str = ""
    seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def cost_usd(self) -> float | None:
        rates = PRICING.get(self.model)
        if rates is None:
            return None
        in_rate, out_rate = rates
        return (self.input_tokens * in_rate + self.output_tokens * out_rate) / 1_000_000

    @property
    def needs_review(self) -> bool:
        return bool(self.problems) or bool(self.fields.uncertain_fields)


class ExtractionError(RuntimeError):
    """Extraction failed, with a message that names what actually went wrong.

    The original app funnelled every failure into "Failed to process document.",
    which made an Anthropic outage and a bug in the caller indistinguishable.
    Everything raised here says which stage failed and what the API returned.
    """


def _validate_last4(raw: str | None) -> tuple[str | None, str | None]:
    """Reduce whatever came back to exactly four digits, or nothing.

    A full card number must never reach the database, even if the model returns
    one. This is a hard boundary, not a formatting preference.
    """
    if not raw:
        return None, None
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        return None, f"no digits in card field {raw!r}"
    if len(digits) > 4:
        return digits[-4:], (
            f"model returned {len(digits)} digits for the card; "
            f"stored only the last 4"
        )
    if len(digits) < 4:
        return digits.rjust(4, "0"), f"card field {raw!r} held only {len(digits)} digits"
    return digits, None


def _parse_date(fields: ReceiptFields) -> tuple[date | None, str | None]:
    if fields.purchased_on:
        try:
            return date.fromisoformat(fields.purchased_on.strip()), None
        except ValueError:
            pass
    raw = (fields.purchased_on_raw or fields.purchased_on or "").strip()
    for pattern in ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y",
                    "%d %b %Y", "%b %d %Y", "%b %d, %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, pattern).date(), f"date read from {raw!r}"
        except ValueError:
            continue
    if raw:
        return None, f"could not read a date from {raw!r}"
    return None, "no date found on the receipt"


def interpret(fields: ReceiptFields) -> Extraction:
    """Turn what the model reported into checked values. No network."""
    notes: dict[str, str] = {}
    problems: list[str] = []

    subtotal, notes["subtotal"] = amounts.interpret_money(fields.subtotal_raw)
    tax, notes["tax"] = amounts.interpret_money(fields.tax_raw)
    total, notes["total"] = amounts.interpret_money(fields.total_raw)

    # A receipt with no tip line is not a receipt with a missing tip — it is a
    # shop, not a restaurant. Settling that here, before reconciliation, stops
    # the derivation logic from "recovering" a tip nobody was ever asked for
    # and flagging a clean receipt for review.
    if fields.tip_raw is None:
        tip, notes["tip"] = Decimal("0.00"), "no tip line on this receipt"
    else:
        tip, notes["tip"] = amounts.interpret_tip(fields.tip_raw)

    checked, problems = amounts.reconcile(subtotal, tax, tip, total)

    last4, last4_note = _validate_last4(fields.card_last4)
    if last4_note:
        notes["card_last4"] = last4_note
        if "only the last 4" in last4_note:
            problems.append(last4_note)

    purchased, date_note = _parse_date(fields)
    if date_note:
        notes["purchased_on"] = date_note
    if purchased is None:
        problems.append(date_note or "no purchase date")
    elif purchased > date.today():
        problems.append(f"purchase date {purchased.isoformat()} is in the future")

    if fields.uncertain_fields:
        problems.append(
            "model reported low confidence in: " + ", ".join(fields.uncertain_fields)
        )

    return Extraction(
        fields=fields,
        amounts=checked,
        notes={k: v for k, v in notes.items() if v},
        problems=problems,
        purchased_on=purchased,
        card_last4=last4,
    )


#: A response that fails to parse as JSON is retried once before being reported
#: as a failure. Measured live on claude-opus-5: a receipt that failed with
#: "EOF while parsing a string" — the same repetition-loop shape the SE Demo
#: Generator's README documented for a small local model, this time from a
#: large hosted one — succeeded cleanly on retry, twice. A malformed response
#: is not billed as a usable extraction either way, so one retry is nearly
#: free insurance against what appears to be sampling noise, not a systematic
#: fault worth surfacing to the person scanning a receipt.
MALFORMED_RESPONSE_RETRIES = 1


def extract_from_bytes(
    image_bytes: bytes,
    media_type: str = images.API_MEDIA_TYPE,
    model: str = DEFAULT_MODEL,
    client: anthropic.Anthropic | None = None,
) -> Extraction:
    """Send one prepared image to Claude and interpret what comes back."""
    client = client or anthropic.Anthropic()
    encoded = base64.standard_b64encode(image_bytes).decode("ascii")

    request = {
        "model": model,
        "max_tokens": 4096,
        "system": SYSTEM_PROMPT,
        "output_format": ReceiptFields,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": encoded,
                    },
                },
                {
                    "type": "text",
                    "text": (
                        "Transcribe this receipt. Report the tip and total "
                        "boxes exactly as they appear, including any "
                        "handwriting."
                    ),
                },
            ],
        }],
    }

    last_malformed: Exception | None = None
    for attempt in range(MALFORMED_RESPONSE_RETRIES + 1):
        started = time.monotonic()
        try:
            response = client.messages.parse(**request)
        except anthropic.AuthenticationError as exc:
            raise ExtractionError(
                "the Anthropic API rejected the credentials — set "
                f"ANTHROPIC_API_KEY or run `ant auth login` ({exc.status_code})"
            ) from exc
        except anthropic.RateLimitError as exc:
            retry = exc.response.headers.get("retry-after", "unknown")
            raise ExtractionError(
                f"rate limited by the Anthropic API; retry after {retry}s"
            ) from exc
        except anthropic.APIStatusError as exc:
            raise ExtractionError(
                f"the Anthropic API returned {exc.status_code}: {exc.message}"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ExtractionError(
                f"could not reach the Anthropic API — check the network ({exc})"
            ) from exc
        except pydantic.ValidationError as exc:
            # messages.parse() raises here when the model's own JSON is
            # malformed — not sent to us broken, generated broken. Retrying
            # sends a fresh request; it is not re-parsing the same bytes.
            last_malformed = exc
            continue
        elapsed = time.monotonic() - started

        if response.stop_reason == "refusal":
            raise ExtractionError("the model declined to read this image")

        parsed = response.parsed_output
        if parsed is None:
            raise ExtractionError(
                f"the model returned no structured output (stop_reason="
                f"{response.stop_reason})"
            )

        result = interpret(parsed)
        result.model = model
        result.seconds = elapsed
        result.input_tokens = response.usage.input_tokens
        result.output_tokens = response.usage.output_tokens
        return result

    raise ExtractionError(
        f"the model's response could not be parsed after "
        f"{MALFORMED_RESPONSE_RETRIES + 1} attempt(s) ({last_malformed})"
    ) from last_malformed


def extract_from_path(
    path: str, model: str = DEFAULT_MODEL, client: anthropic.Anthropic | None = None
) -> Extraction:
    image = images.open_normalized(path)
    payload, media_type = images.for_model(image)
    return extract_from_bytes(payload, media_type, model=model, client=client)


def _money(value: Decimal | None) -> str:
    return "—" if value is None else f"${value:,.2f}"


def _report(path: str, result: Extraction) -> None:
    f = result.fields
    print(f"  vendor        {f.vendor or '—'}")
    print(f"  date          {result.purchased_on or '—'}"
          f"{'   (' + (f.purchased_on_raw or '') + ')' if f.purchased_on_raw else ''}")
    print(f"  subtotal      {_money(result.amounts['subtotal'])}")
    print(f"  tax           {_money(result.amounts['tax'])}")
    print(f"  tip           {_money(result.amounts['tip'])}"
          f"      raw: {f.tip_raw!r}")
    print(f"  total         {_money(result.amounts['total'])}"
          f"      raw: {f.total_raw!r}")
    print(f"  card          {'**** ' + result.card_last4 if result.card_last4 else '—'}"
          f"   {f.payment_method or ''}")
    print(f"  category      {f.category}")
    print(f"  warranty item {'YES — ' + (f.durable_goods_note or '') if f.has_durable_goods else 'no'}")
    print(f"  handwritten   {'yes' if f.handwritten_amounts else 'no'}")
    if f.items:
        print(f"  items         {len(f.items)}")

    if result.notes:
        print("  how it was read")
        for key, note in result.notes.items():
            print(f"    {key}: {note}")

    if result.problems:
        print("  NEEDS REVIEW")
        for problem in result.problems:
            print(f"    - {problem}")
    else:
        print("  clean — amounts reconcile")

    cost = result.cost_usd
    print(f"  {result.model}  {result.seconds:.1f}s  "
          f"{result.input_tokens} in / {result.output_tokens} out"
          f"{f'  ${cost:.4f}' if cost is not None else ''}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read receipt photographs with Claude and check the amounts."
    )
    parser.add_argument("images", nargs="+", help="receipt image files (globs allowed)")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"model id (default {DEFAULT_MODEL})")
    parser.add_argument("--compare", action="store_true",
                        help="run claude-opus-5 and claude-sonnet-5 on each image")
    parser.add_argument("--json", action="store_true",
                        help="print the raw model output as JSON")
    args = parser.parse_args(argv)

    paths: list[str] = []
    for pattern in args.images:
        matched = sorted(glob.glob(pattern))
        paths.extend(matched or [pattern])

    models = ["claude-opus-5", "claude-sonnet-5"] if args.compare else [args.model]
    client = anthropic.Anthropic()

    failures = 0
    totals: dict[str, list[float]] = {m: [] for m in models}
    for path in paths:
        print(f"\n{path}")
        print("=" * 72)
        for model in models:
            if len(models) > 1:
                print(f"\n[{model}]")
            try:
                result = extract_from_path(path, model=model, client=client)
            except (ExtractionError, ValueError) as exc:
                failures += 1
                print(f"  FAILED: {exc}")
                continue
            if args.json:
                print(result.fields.model_dump_json(indent=2))
            _report(path, result)
            if result.cost_usd is not None:
                totals[model].append(result.cost_usd)

    print()
    for model, costs in totals.items():
        if costs:
            print(f"{model}: {len(costs)} receipts, "
                  f"${sum(costs):.4f} total, ${sum(costs) / len(costs):.4f} each")
    if failures:
        print(f"{failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
