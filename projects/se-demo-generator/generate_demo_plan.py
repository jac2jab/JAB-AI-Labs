"""SE Demo Generator — discovery notes to a deal-ready demo plan.

    python generate_demo_plan.py --notes data/sample_discovery_notes.md --vendor generic

Two stages, deliberately separated:

  1. EXTRACT   unstructured notes -> a structured opportunity profile
  2. GENERATE  profile + vendor pack -> demo plan, talk tracks, positioning

They are separate because they fail differently. Extraction failing means the
notes were thin. Generation failing usually means the vendor pack is thin. One
combined call hides which.

Stage 1 was validated in May 2026 against a constructed enterprise-security
scenario. Stage 2 is what this program adds.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from llm import ModelUnavailable, complete
from packs import available_packs, load_metadata, load_pack, pack_status
from solution_areas import classify, counterparts

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"


EXTRACT_SYSTEM = """You are an experienced enterprise sales engineer reading \
discovery notes.

Extract only what the notes actually say. Do not infer a budget that was not \
mentioned, a timeline that was not stated, or a competitor that was not named.

Separate what the customer stated from what you are inferring. An empty field \
is more useful to a colleague than a plausible guess.

Reply with JSON only. No preamble, no code fence."""


# Passed to the backend so decoding is constrained to this shape. The prompt
# still describes the fields — the schema guarantees the structure, the prompt
# explains what belongs in each field.
_STRINGS = {"type": "array", "items": {"type": "string"}}

PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "account": {"type": "string"},
        "stated_pains": _STRINGS,
        "current_environment": _STRINGS,
        "incumbent_vendors": _STRINGS,
        "competitors_mentioned": _STRINGS,
        "stakeholders": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "role": {"type": "string"},
                    "concern": {"type": "string"},
                },
                "required": ["role", "concern"],
            },
        },
        "compliance_or_constraints": _STRINGS,
        "budget_signal": {"type": "string"},
        "timeline_signal": {"type": "string"},
        "compelling_event": {"type": "string"},
        "inferences": _STRINGS,
        "missing_information": _STRINGS,
    },
    "required": [
        "account", "stated_pains", "current_environment", "incumbent_vendors",
        "competitors_mentioned", "stakeholders", "compliance_or_constraints",
        "budget_signal", "timeline_signal", "compelling_event", "inferences",
        "missing_information",
    ],
}


EXTRACT_TEMPLATE = """Extract a structured opportunity profile from these \
discovery notes.

Return exactly this JSON shape:

{{
  "account": "",
  "stated_pains": [],
  "current_environment": [],
  "incumbent_vendors": [],
  "competitors_mentioned": [],
  "stakeholders": [{{"role": "", "concern": ""}}],
  "compliance_or_constraints": [],
  "budget_signal": "",
  "timeline_signal": "",
  "compelling_event": "",
  "inferences": [],
  "missing_information": []
}}

Use "" or [] for anything the notes do not establish. Put your own reasoning \
in "inferences", and put what you would ask next in "missing_information".

DISCOVERY NOTES
---
{notes}
---"""


GENERATE_SYSTEM = """You are a principal sales engineer preparing a colleague \
to run a demo.

Ground every recommendation in the vendor knowledge provided. If the knowledge \
does not cover something the opportunity needs, say so plainly under a "Gaps" \
heading rather than inventing a capability. A brief that promises something \
undemoable gets an SE caught out in the room.

Be specific and concrete. "Show the dashboard" is useless; "open the executive \
risk view and filter to the last 30 days to show the reduction" is a demo step.

Write in Markdown."""


# Generation is split into groups rather than requested as one document.
#
# A single call producing all seven sections is roughly 1,500 words, which on a
# CPU-bound local model exceeded a five-minute timeout and lost everything —
# including the extraction that had already succeeded. Grouping bounds each
# call, shows progress, and means one slow section cannot discard the rest.
#
# Grouped rather than one call per section because the profile and vendor
# knowledge are re-sent with every call; seven calls would re-process that
# context seven times.
#
# Each group also declares the headings it owns. The model does not reliably
# honour "produce exactly these sections and nothing else" — the first run
# emitted a Gaps section from group one and again from group three, so the
# document had two. The contract is enforced in code instead.
SECTION_GROUPS: list[tuple[str, list[str], str]] = [
    (
        "demo flow",
        ["Opportunity Summary", "Recommended Demo Flow"],
        """## Opportunity Summary
Two or three sentences. What is the deal, and what has to be true to win it?

## Recommended Demo Flow
Numbered steps. For each: what to show, and the reason it earns its place in \
this specific deal. Tie steps back to the customer's stated pains.""",
    ),
    (
        "talk tracks",
        ["Executive Talk Track", "Technical Talk Track"],
        """## Executive Talk Track
What you say to the economic buyer. Business outcomes, not features.

## Technical Talk Track
What you say to the technical evaluator. Specific, and honest about limits.""",
    ),
    (
        "positioning and gaps",
        ["Competitive Positioning", "Questions To Ask", "Gaps"],
        """## Competitive Positioning
Only for competitors actually named in the profile. Where they are genuinely \
strong, and where the difference shows.

## Questions To Ask
The questions that advance this deal, drawn from the discovery gaps.

## Gaps
What the vendor pack does not cover that this opportunity needs. Be direct — \
this section tells the SE what to go find out.""",
    ),
]


GENERATE_TEMPLATE = """Build part of a demo plan for this opportunity.

Produce exactly these sections and nothing else. Do not add a preamble, a \
conclusion, or sections that were not asked for.

{sections}

OPPORTUNITY PROFILE
---
{profile}
---

VENDOR KNOWLEDGE
---
{knowledge}
---"""


def parse_json_response(text: str) -> dict:
    """Parse a JSON object from a model response, tolerating stray wrapping.

    Small local models often add a code fence or a sentence of preamble despite
    instructions, so fall back to the outermost braces before giving up.
    """
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start, end = text.find("{"), text.rfind("}")

    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(
        "Could not parse an opportunity profile from the model response.\n"
        f"First 300 characters:\n{text[:300]}"
    )


def normalize_profile(profile: dict) -> dict:
    """Coerce a parsed profile to the expected shape.

    JSON mode guarantees the response parses, not that it carries every field
    or the right types for them. Filling gaps here means the rest of the
    program can index the profile without defensive checks at every use.
    """
    normalized = {}

    for field, spec in PROFILE_SCHEMA["properties"].items():
        value = profile.get(field)

        if spec["type"] == "array":
            if not isinstance(value, list):
                value = [] if value in (None, "") else [value]
            # A model will sometimes emit bare strings where objects belong.
            if field == "stakeholders":
                value = [
                    item if isinstance(item, dict) else {"role": str(item), "concern": ""}
                    for item in value
                ]
            else:
                value = [str(item) for item in value if item not in (None, "")]
        else:
            value = "" if value is None else str(value)

        normalized[field] = value

    # Keep anything extra the model volunteered rather than silently dropping it.
    for field, value in profile.items():
        normalized.setdefault(field, value)

    return normalized


def extract_profile(notes: str) -> tuple[dict, str]:
    """Stage 1 — turn unstructured notes into a structured profile."""
    response, backend = complete(
        EXTRACT_SYSTEM,
        EXTRACT_TEMPLATE.format(notes=notes),
        json_schema=PROFILE_SCHEMA,
    )
    return normalize_profile(parse_json_response(response)), backend


def keep_requested_sections(markdown: str, headings: list[str]) -> str:
    """Keep only the H2 sections a group was asked to produce.

    Small models add sections they were not asked for and drop preambles in
    front of the first heading. Filtering here keeps each group's output inside
    its contract, so groups cannot emit overlapping sections.
    """
    wanted = {heading.strip().lower() for heading in headings}

    kept: list[str] = []
    current: list[str] | None = None

    for line in markdown.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)

        if match:
            if current:
                kept.append("\n".join(current).rstrip())
            title = match.group(1).strip().lower()
            current = [line] if title in wanted else None
            continue

        if current is not None:
            current.append(line)

    if current:
        kept.append("\n".join(current).rstrip())

    return "\n\n".join(kept)


def generate_plan(profile: dict, knowledge: str) -> tuple[str, str, list[str]]:
    """Stage 2 — turn the profile plus vendor knowledge into a demo plan.

    Runs one call per section group. A group that fails is reported rather than
    aborting the run, so a partial plan still reaches the user with the missing
    parts named.
    """
    profile_json = json.dumps(profile, indent=2)
    knowledge = knowledge or "(No vendor pack content written yet.)"

    parts: list[str] = []
    failed: list[str] = []
    backend = "unknown"

    for label, headings, sections in SECTION_GROUPS:
        print(f"                 ...{label}", flush=True)

        try:
            text, backend = complete(
                GENERATE_SYSTEM,
                GENERATE_TEMPLATE.format(
                    sections=sections,
                    profile=profile_json,
                    knowledge=knowledge,
                ),
            )
            parts.append(keep_requested_sections(text, headings))
        except ModelUnavailable as error:
            failed.append(f"{label} ({error})")

    return "\n\n".join(part for part in parts if part), backend, failed


def render(
    plan: str,
    profile: dict,
    status: dict,
    metadata: dict,
    backend: str,
    failed: list[str] | None = None,
) -> str:
    """Assemble the output document, provenance included."""
    today = datetime.now().strftime("%B %d, %Y")
    display = metadata.get("display_name") or status["vendor"]

    coverage = (
        f"{status['percent_complete']}% "
        f"({len(status['written'])}/{status['total']} sections written)"
    )

    header = [
        f"# Demo Plan — {profile.get('account') or 'Unnamed account'}",
        "",
        f"**Vendor pack:** {display} · {coverage}  ",
        f"**Generated:** {today} by `{backend}`",
        "",
    ]

    if status["percent_complete"] < 100:
        thin = ", ".join(
            name.replace(".md", "") for name in (status["skeleton"] + status["missing"])
        )
        header += [
            "> **Pack is incomplete.** Unwritten sections were not sent to the",
            f"> model, so the plan below is thinner than it could be: {thin}.",
            "",
        ]

    if failed:
        header += [
            f"> **{len(failed)} section group(s) failed to generate:** "
            f"{'; '.join(failed)}.",
            "",
        ]

    body = [plan, "", "---", "", "## Extracted Opportunity Profile", "",
            "```json", json.dumps(profile, indent=2), "```", ""]

    return "\n".join(header + body)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Turn discovery notes into a deal-ready demo plan."
    )
    parser.add_argument(
        "--notes",
        type=Path,
        default=BASE_DIR / "data" / "sample_discovery_notes.md",
        help="Discovery notes file (text or Markdown).",
    )
    parser.add_argument(
        "--vendor",
        default=(available_packs() or ["trend-micro"])[0],
        help=f"Vendor pack to use. Available: {', '.join(available_packs()) or 'none'}",
    )
    args = parser.parse_args()

    try:
        if not args.notes.exists():
            raise FileNotFoundError(f"Notes file not found: {args.notes}")

        notes = args.notes.read_text(encoding="utf-8").strip()

        if not notes:
            raise ValueError(f"{args.notes} is empty.")

        status = pack_status(args.vendor)
        metadata = load_metadata(args.vendor)

        print(f"Notes:        {args.notes.name} ({len(notes.split())} words)")
        print(f"Vendor pack:  {args.vendor} — {status['percent_complete']}% written "
              f"({len(status['written'])}/{status['total']} sections)")

        if status["skeleton"] or status["missing"]:
            unwritten = status["skeleton"] + status["missing"]
            print(f"              unwritten: {', '.join(n.replace('.md','') for n in unwritten)}")

        print()
        print("Stage 1 — extracting opportunity profile...")
        profile, backend = extract_profile(notes)

        found = sum(1 for value in profile.values() if value)
        print(f"              {found}/{len(profile)} fields populated")

        # Narrow the demo flows to the solution areas this opportunity actually
        # calls for. A multi-product vendor has one flow per area, and
        # injecting all of them buries the relevant one.
        #
        # Two mechanisms, because they fail differently. The classifier reads
        # the whole profile and handles phrasing nobody anticipated; the
        # trigger floor fires on unambiguous strings whatever the classifier
        # decided. Neither is trusted alone.
        signals = [
            str(item)
            for key in ("stated_pains", "current_environment", "compelling_event")
            for item in (
                profile.get(key, [])
                if isinstance(profile.get(key), list)
                else [profile.get(key, "")]
            )
        ]

        print("Stage 1b — classifying solution areas...")
        try:
            areas, detail, area_backend = classify(profile)
        except ModelUnavailable as error:
            # Not fatal. Trigger matching still selects flows without this, so
            # a classifier failure degrades the selection rather than the run.
            areas, detail = [], {"why": {}, "dropped": []}
            print(f"              classifier unavailable ({error}); triggers only")
        else:
            if areas:
                for area in areas:
                    reason = (detail["why"] or {}).get(area, "")
                    print(f"              {area}" + (f" - {reason}" if reason else ""))
            else:
                print("              no area identified; triggers only")

            if detail["dropped"]:
                # Labels outside SOLUTION_AREAS, discarded in code. Printed
                # because a model reaching for an area the vendor has no label
                # for is a signal about the label set, not just noise.
                print(f"              discarded (not a known area): "
                      f"{', '.join(detail['dropped'])}")

            missing = counterparts(areas)
            if missing:
                # Posture without response, or the reverse. Not added to the
                # plan - just named, because whether the demo should cover
                # both is the SE's call, not the tool's.
                print(f"              no counterpart flow selected for: "
                      f"{', '.join(missing)}")

        knowledge, _, selected_areas = load_pack(args.vendor, signals, areas)

        if selected_areas:
            print(f"              demo flows selected: {', '.join(selected_areas)}")

        print("Stage 2 — generating demo plan...")
        plan, backend, failed = generate_plan(profile, knowledge)

        if failed:
            print(f"              {len(failed)} section group(s) failed: "
                  f"{'; '.join(failed)}")

        if not plan.strip():
            raise ModelUnavailable(
                "Every section group failed — no plan was produced."
            )

        document = render(plan, profile, status, metadata, backend, failed)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        account = re.sub(r"[^a-z0-9]+", "-", (profile.get("account") or "account").lower()).strip("-")
        output_file = OUTPUT_DIR / f"demo_plan_{account}_{datetime.now():%Y-%m-%d}.md"
        output_file.write_text(document, encoding="utf-8")

        print()
        print(f"Backend:      {backend}")
        print(f"Written to:   {output_file}")

    except ModelUnavailable as error:
        print(f"\n{error}", file=sys.stderr)
        raise SystemExit(1)
    except (FileNotFoundError, ValueError) as error:
        print(f"\n{error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
