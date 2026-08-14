"""Vendor pack schema, loading, and completeness reporting.

A vendor pack is the institutional knowledge of a strong sales engineer,
written down: which demo flows actually win, how the product is really
positioned against a competitor, which discovery answers map to which
capability, what a POC has to prove.

That knowledge is the moat. The generation layer is commodity — any SE can
paste notes into a chatbot and get a summary. What they will not do is curate,
maintain, and standardize this across a team.

Everything the generator knows about a vendor comes from these files, so the
schema is defined once here and used for three things: scaffolding a new pack,
validating an existing one, and loading it for generation.
"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PACKS_DIR = BASE_DIR / "vendor_packs"

# `generic` is not a vendor. It holds the vendor-agnostic SE playbook that
# loads alongside every pack, so it must not be scaffolded or selected as one.
RESERVED_NAMES = frozenset({"generic"})

# Marks a section that still holds template prompts rather than real content.
# Written into every scaffolded file and stripped when the section is answered.
UNWRITTEN_MARKER = "<!-- UNWRITTEN -->"


# Each section carries the question it exists to answer. A blank file is
# paralyzing; a file that asks a specific question is a form to fill in.
SECTIONS: dict[str, dict[str, str]] = {
    "product_capabilities.md": {
        "title": "Product Capabilities",
        "purpose": "What the product actually does, in the words a customer uses.",
        "prompts": (
            "- What are the 5-8 capabilities that come up in almost every deal?\n"
            "- For each, what customer problem does it solve? Lead with the problem.\n"
            "- Which capabilities are genuinely differentiated, and which are table stakes?\n"
            "- What does the product deliberately NOT do? Knowing this prevents\n"
            "  the generator from promising something you cannot demo."
        ),
    },
    "demo_flows.md": {
        "title": "Demo Flows",
        "purpose": "The sequences that actually win deals — not a product tour.",
        "prompts": (
            "This is the highest-value file in the pack. Write the flows you would\n"
            "run, in order, with the reason each step earns its place.\n\n"
            "- What is the opening move that earns attention in the first 3 minutes?\n"
            "- What is the sequence of screens or actions, numbered?\n"
            "- Where does the demo usually go wrong, and how do you recover?\n"
            "- What is the closing moment that makes the decision obvious?\n"
            "- Which flow do you run for a technical audience vs an executive one?"
        ),
    },
    "competitor_positioning.md": {
        "title": "Competitor Positioning",
        "purpose": "How this product is really positioned against each rival.",
        "prompts": (
            "- Who do you actually run into in deals? Name them.\n"
            "- For each: where are they genuinely strong? Say it honestly — a\n"
            "  brief that pretends a competitor is weak everywhere gets an SE\n"
            "  caught out in the room.\n"
            "- Where do their customers get frustrated, in their own words?\n"
            "- What is the one question that surfaces the difference without\n"
            "  sounding like an attack?"
        ),
    },
    "discovery_questions.md": {
        "title": "Discovery Questions",
        "purpose": "The questions that reveal whether there is a real deal here.",
        "prompts": (
            "- What do you ask to size the problem?\n"
            "- What do you ask to find the compelling event? No event, no deal.\n"
            "- What do you ask to identify the economic buyer vs the champion?\n"
            "- Which answers should make you walk away or disqualify?\n"
            "- Map each question to what a given answer tells you."
        ),
    },
    "common_use_cases.md": {
        "title": "Common Use Cases",
        "purpose": "Pain the customer states, mapped to the capability that answers it.",
        "prompts": (
            "Write these as pain -> capability -> proof:\n\n"
            "- What does the customer say out loud when they have this problem?\n"
            "- Which capability addresses it?\n"
            "- What would you show to prove it, in one demo step?\n\n"
            "This mapping is what lets the generator connect messy discovery\n"
            "notes to a concrete demo plan."
        ),
    },
    "objection_handling.md": {
        "title": "Objection Handling",
        "purpose": "What they push back on, and what actually answers it.",
        "prompts": (
            "- What are the objections you hear in nearly every deal?\n"
            "- For each: what is the real concern underneath the stated one?\n"
            "- What response has actually worked for you?\n"
            "- Which objections are legitimate and should be conceded rather than\n"
            "  argued? Conceding a real gap builds more credibility than deflecting."
        ),
    },
    "customer_personas.md": {
        "title": "Customer Personas",
        "purpose": "Who is in the room, and what each of them needs to hear.",
        "prompts": (
            "- Who attends these meetings? Title, and what they are measured on.\n"
            "- What does each one care about, and what bores them?\n"
            "- Who can say yes, who can only say no, and who is the champion?\n"
            "- How does the message change between the technical and executive audience?"
        ),
    },
    "poc_playbooks.md": {
        "title": "POC Playbooks",
        "purpose": "What a proof of concept must prove, and how it is scoped.",
        "prompts": (
            "- What are the success criteria a POC should be scoped to? Be specific\n"
            "  and measurable — 'improve security' is not a criterion.\n"
            "- How long should it run, and what does the customer need to provide?\n"
            "- What causes POCs to stall or die?\n"
            "- What is the exit — how does a successful POC convert to a decision?"
        ),
    },
    "deployment_patterns.md": {
        "title": "Deployment Patterns",
        "purpose": "How this actually gets deployed in real environments.",
        "prompts": (
            "- What are the common architectures customers land on?\n"
            "- What does the customer's environment need to look like?\n"
            "- Which integrations come up every time?\n"
            "- What sizing or scaling questions should be asked early?"
        ),
    },
    "implementation_gotchas.md": {
        "title": "Implementation Gotchas",
        "purpose": "What bites people after the deal closes.",
        "prompts": (
            "- What surprises customers during rollout?\n"
            "- What should be raised before the sale to avoid a bad outcome after it?\n"
            "- Which environments or edge cases cause trouble?\n"
            "- What does a bad deployment look like, and what causes it?"
        ),
    },
    "api_examples.md": {
        "title": "API and Integration Examples",
        "purpose": "Concrete technical proof for a technical audience.",
        "prompts": (
            "- What API calls or integrations do you demo?\n"
            "- What is the smallest working example that proves extensibility?\n"
            "- Which integrations do customers ask about most?\n"
            "- Leave this thin if the product is not API-led — an honest gap beats\n"
            "  filler."
        ),
    },
}

METADATA_FILE = "metadata.json"


def metadata_template(vendor: str) -> dict:
    """Default metadata for a newly scaffolded pack."""
    return {
        "vendor": vendor,
        "display_name": vendor.replace("-", " ").title(),
        "category": "",
        "author": "",
        "last_reviewed": "",
        "notes": "Set category (e.g. 'endpoint security'), author, and review date.",
    }


def section_template(filename: str) -> str:
    """Render the skeleton for one section: the question, not a blank page."""
    section = SECTIONS[filename]

    return (
        f"# {section['title']}\n\n"
        f"> {section['purpose']}\n\n"
        f"{UNWRITTEN_MARKER}\n"
        f"## Answer these, then delete this block and the marker above\n\n"
        f"{section['prompts']}\n"
    )


def is_written(text: str) -> bool:
    """A section counts as written once the template marker is removed."""
    return UNWRITTEN_MARKER not in text and text.strip() != ""


def available_packs() -> list[str]:
    """List vendor pack directories, excluding the shared generic playbook."""
    if not PACKS_DIR.exists():
        return []

    return sorted(
        path.name
        for path in PACKS_DIR.iterdir()
        if path.is_dir()
        and not path.name.startswith("_")
        and path.name not in RESERVED_NAMES
    )


def pack_status(vendor: str) -> dict:
    """Report which sections of a pack are written, missing, or still skeleton."""
    pack_dir = PACKS_DIR / vendor

    if not pack_dir.is_dir():
        raise FileNotFoundError(f"No vendor pack named '{vendor}' in {PACKS_DIR}")

    written, skeleton, missing = [], [], []

    for filename in SECTIONS:
        path = pack_dir / filename

        if not path.exists():
            missing.append(filename)
        elif is_written(path.read_text(encoding="utf-8")):
            written.append(filename)
        else:
            skeleton.append(filename)

    return {
        "vendor": vendor,
        "written": written,
        "skeleton": skeleton,
        "missing": missing,
        "total": len(SECTIONS),
        "percent_complete": round(100 * len(written) / len(SECTIONS)),
    }


def load_pack(vendor: str) -> tuple[str, dict]:
    """Load a vendor pack's written sections into one knowledge block.

    Skeleton sections are skipped rather than passed to the model — template
    questions in the prompt would be answered as if they were content.
    """
    pack_dir = PACKS_DIR / vendor

    if not pack_dir.is_dir():
        raise FileNotFoundError(
            f"No vendor pack named '{vendor}'. Available: "
            f"{', '.join(available_packs()) or 'none'}"
        )

    status = pack_status(vendor)
    parts = []

    generic = PACKS_DIR / "generic" / "se_playbook.md"
    if generic.exists():
        parts.append(f"# Sales Engineering Playbook (vendor-agnostic)\n\n{generic.read_text(encoding='utf-8')}")

    for filename in status["written"]:
        parts.append((pack_dir / filename).read_text(encoding="utf-8"))

    return "\n\n---\n\n".join(parts), status


def load_metadata(vendor: str) -> dict:
    """Load a pack's metadata, tolerating a missing or malformed file."""
    path = PACKS_DIR / vendor / METADATA_FILE

    if not path.exists():
        return metadata_template(vendor)

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return metadata_template(vendor)
