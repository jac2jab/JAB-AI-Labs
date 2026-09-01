"""Classify an opportunity profile into the vendor's solution areas.

THE PROBLEM THIS SOLVES

`select_demo_flows` originally had one mechanism: substring-match the phrases
in a flow's `**Triggered by:**` line against the extracted profile. That works
right up until you try to write the trigger list, at which point you are trying
to enumerate every phrasing a customer might use for eight solution areas. The
set does not close.

Measured, on the sample discovery notes: the first seven triggers written for
the Endpoint flow scored 0 of 7, because they were written the way an SE
summarises a pain ("too many alerts") and the customer had said "We get 400
alerts a day and triage maybe 40". Same concept, no shared substring.

This is the wall the Daily Brief hit with keyword relevance scoring, and the
fix is the same one: stop enumerating the inputs, enumerate the outputs. The
areas a demo can cover is a closed list of eight. So the model classifies into
that list, and the code enforces membership.

WHAT IS ASKED OF THE MODEL, AND WHAT IS NOT

Asked:      which of these eight areas does this opportunity call for.
Not asked:  which flow to show, how to rank the plan, whether the pack is
            complete, or anything requiring a number.

The model returns labels from a fixed list and nothing else. Membership is
filtered here, the cap is applied here, and the ordering the model supplies is
used only to decide what falls off the end. Same division as relevance.py,
where the model picks a category and the arithmetic is a dict in code.

WHY THIS IS A SEPARATE CALL AND NOT A FIELD ON THE EXTRACTION

Because the Daily Brief already measured what happens when two judgments share
a prompt: asked as a yes/no beside the relevance questions, the furniture
answers and the relevance answers moved together - one prompt made everything
furniture and nothing relevant, the next the exact reverse. Extraction is a
reading task and classification is a judgment task, and they get their own
calls. Measured on llama3.2 against the sample notes: extraction 108s,
classification 20s. A fifth of a minute on top of a run whose generation stage
is measured in minutes.
"""

import json
import re

from llm import ModelUnavailable, complete
from packs import MAX_SELECTED_AREAS, SOLUTION_AREAS

# This answer is a handful of labels and one short line each. The project-wide
# cap is sized for a prose section group, and inheriting it here would let a
# discursive run spend minutes on a call that should take seconds. Measured on
# llama3.2: this call returned in 20s well inside the cap, so it is a guard
# rather than a fix for something observed.
CLASSIFY_MAX_TOKENS = 300

SYSTEM = (
    "You are a sales engineer deciding which parts of a security platform a "
    "customer's discovery call actually calls for.\n\n"
    "Choose only from the areas you are given. Do not invent an area, do not "
    "rename one, and do not choose an area because the vendor sells it - "
    "choose it because something in this profile points at it. If the profile "
    "only supports one area, return one. Returning fewer, correct areas is "
    "better than returning more."
)


def _catalogue() -> str:
    """The closed set, with each area defined in customer language."""
    return "\n".join(
        f"- {label} ({spec['mode']}): {spec['says']}"
        for label, spec in SOLUTION_AREAS.items()
    )


def _prompt_for(profile: dict) -> str:
    """Build the classification prompt for one opportunity profile."""
    def block(key: str) -> str:
        value = profile.get(key) or []
        if not isinstance(value, list):
            value = [value]
        return "\n".join(f"- {item}" for item in value if item) or "- (none recorded)"

    stakeholders = profile.get("stakeholders") or []
    roles = "\n".join(
        f"- {s.get('role', '')}: {s.get('concern', '')}".rstrip(": ")
        for s in stakeholders
        if isinstance(s, dict) and s.get("role")
    ) or "- (none recorded)"

    return (
        f"SOLUTION AREAS:\n{_catalogue()}\n\n"
        f"STATED PAINS:\n{block('stated_pains')}\n\n"
        f"CURRENT ENVIRONMENT:\n{block('current_environment')}\n\n"
        f"WHO IS IN THE ROOM:\n{roles}\n\n"
        f"COMPLIANCE AND CONSTRAINTS:\n{block('compliance_or_constraints')}\n\n"
        f"COMPELLING EVENT:\n- {profile.get('compelling_event') or '(none recorded)'}\n\n"
        "Reply with exactly this JSON object and nothing else:\n"
        "{\n"
        '  "areas": ["most strongly supported area first"],\n'
        '  "why": {"Area label": "the words in the profile that put it there"}\n'
        "}"
    )


def _parse(response: str) -> tuple[list[str], dict]:
    """Pull the areas out of a model response, tolerating stray prose."""
    text = response.strip()

    if not text.startswith("{"):
        match = re.search(r"\{.*\}", text, re.DOTALL)
        text = match.group(0) if match else "{}"

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [], {}

    areas = data.get("areas") or []
    if isinstance(areas, str):
        areas = [areas]

    why = data.get("why") if isinstance(data.get("why"), dict) else {}

    return [str(a) for a in areas], why


def enforce(areas: list[str]) -> list[str]:
    """Keep only real areas, de-duplicated, capped, order preserved.

    The model is asked for labels from a fixed list. Whether it honoured that
    is not taken on trust - a label that is not in SOLUTION_AREAS is dropped
    here, the same way keep_requested_sections drops a heading a group was not
    asked to produce. Matching is case-insensitive so "cspm" is accepted for
    "CSPM", but nothing else is normalised: a near-miss is a miss.
    """
    canonical = {label.lower(): label for label in SOLUTION_AREAS}

    kept: list[str] = []
    for area in areas:
        label = canonical.get(area.strip().lower())
        if label and label not in kept:
            kept.append(label)

    return kept[:MAX_SELECTED_AREAS]


def counterparts(areas: list[str]) -> list[str]:
    """The posture/response partners of the selected areas, where declared.

    Posture answers "how do I stop being surprised" and response answers "what
    happens when it lands". A plan that shows only one leaves the customer's
    other question open, and which pairing is right is SE judgment - so this
    reads `pairs_with` and never infers it. Areas already selected are not
    repeated, and this does not itself add them to the plan; the caller
    decides.
    """
    selected = set(areas)

    return [
        partner
        for area in areas
        if (partner := SOLUTION_AREAS.get(area, {}).get("pairs_with"))
        and partner not in selected
        and partner not in areas
    ]


def classify(profile: dict) -> tuple[list[str], dict, str]:
    """Classify a profile into solution areas.

    Returns the areas, the model's stated reason per area, and the backend.
    Raises ModelUnavailable if no backend can serve the request - the caller
    decides whether that is fatal, because trigger matching still works
    without this and a pack with good triggers degrades rather than dies.
    """
    response, backend = complete(
        SYSTEM,
        _prompt_for(profile),
        json_schema={
            "type": "object",
            "properties": {
                "areas": {"type": "array", "items": {"type": "string"}},
                "why": {"type": "object"},
            },
            "required": ["areas"],
        },
        max_tokens=CLASSIFY_MAX_TOKENS,
    )

    raw, why = _parse(response)
    areas = enforce(raw)

    dropped = [a for a in raw if a not in areas]

    return areas, {"why": why, "dropped": dropped}, backend
