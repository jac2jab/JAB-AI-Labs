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
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PACKS_DIR = BASE_DIR / "vendor_packs"

# `generic` is not a vendor. It holds the vendor-agnostic SE playbook that
# loads alongside every pack, so it must not be scaffolded or selected as one.
RESERVED_NAMES = frozenset({"generic"})

# Marks a section that still holds template prompts rather than real content.
# Written into every scaffolded file and stripped when the section is answered.
UNWRITTEN_MARKER = "<!-- UNWRITTEN -->"


# The vendor's solution areas, defined once and used for four things: the
# closed set the classifier may choose from, the vocabulary for `## ` headings
# in demo_flows.md and competitor_positioning.md, the universal trigger floor,
# and the posture/response pairing below.
#
# WHY A CLASSIFIER RATHER THAN A LONGER TRIGGER LIST
# The set of things a customer might say is unbounded, so a hand-kept list of
# phrases cannot close it - the same wall the Daily Brief hit with keyword
# relevance scoring. What IS bounded is this list: the areas a demo can cover.
# So a model classifies the profile into these labels and the code enforces
# membership, exactly as relevance.py picks one of six categories and never
# emits a score.
#
# `says` is the definition the classifier is given, and it is deliberately
# written in CUSTOMER language rather than product language. CSPM, DSPM and
# Workload Security are three products but one word ("cloud") in a customer's
# mouth; described by what the customer complains about they separate cleanly,
# described by product name they collapse into each other.
#
# `triggers` are the universal precision floor - unambiguous strings that
# select an area whatever the classifier decides. They do NOT need to be
# exhaustive; that is the classifier's job now. They only need to be correct.
# Kept short and acronym-shaped on purpose: a bare `soc` was tried and fired on
# "social engineering", "SOC 2" and "associate". A pack's own
# `**Triggered by:**` line adds vendor- and deal-specific phrases on top.
#
# `pairs_with` is the proactive/reactive counterpart. Posture answers "how do I
# stop being surprised", response answers "what happens when it lands", and a
# plan carrying only one of the two leaves the other question hanging. `None`
# means the pairing is not decided yet - it is SE judgment, so it is left blank
# rather than guessed.
SOLUTION_AREAS: dict[str, dict] = {
    "EDR/XDR": {
        "mode": "response",
        "says": (
            "Too many alerts to triage, no way to see how an incident spread "
            "across endpoint, server, email and network, slow investigation, "
            "analysts who take months to become useful, ransomware."
        ),
        "triggers": ("edr", "xdr", "endpoint", "triage", "soc analyst", "soc lead"),
        "pairs_with": "ASRM",
    },
    "ASRM": {
        "mode": "posture",
        "says": (
            "No single view of what is exposed and how risky it is, no way to "
            "show the board whether risk went up or down, cannot tell which "
            "vulnerability exposure to fix first. Gives visibility and "
            "recommendations for vulnerability exposure - it does NOT do "
            "vulnerability management, so do not read patching into it."
        ),
        "triggers": ("asrm", "attack surface", "risk score", "cyber risk"),
        "pairs_with": "EDR/XDR",
    },
    "CSPM": {
        "mode": "posture",
        "says": (
            "Do not know what is exposed or misconfigured in the cloud "
            "accounts, no idea how many accounts there are, compliance "
            "findings against cloud configuration."
        ),
        "triggers": ("cspm", "misconfigur", "cloud posture"),
        "pairs_with": "Workload Security",
    },
    "Workload Security": {
        "mode": "response",
        "says": (
            "Protecting the things actually running - servers, VMs, "
            "containers, Kubernetes. Runtime attacks, unpatched servers that "
            "cannot be taken down, workloads no agent covers."
        ),
        "triggers": ("workload", "container", "kubernetes", "runtime protection"),
        "pairs_with": "CSPM",
    },
    "Email Security": {
        "mode": "response",
        "says": (
            "Users clicking phishing links, business email compromise, "
            "malicious attachments, and what the current gateway misses."
        ),
        "triggers": ("phishing", "email gateway", "business email compromise", "bec"),
        "pairs_with": None,
    },
    "Network Security": {
        "mode": "response",
        "says": (
            "Cannot see what is moving laterally, unmanaged or unagentable "
            "devices, OT and plant networks, intrusion detection and "
            "prevention, east-west traffic."
        ),
        "triggers": ("lateral movement", "east-west", "network detection", "ot network"),
        "pairs_with": None,
    },
    "DSPM": {
        "mode": "posture",
        "says": (
            "Do not know where sensitive data lives, who can reach it, or "
            "whether it left. Data residency and classification."
        ),
        "triggers": ("dspm", "sensitive data", "data classification", "data residency"),
        "pairs_with": None,
    },
    "ISPM": {
        "mode": "posture",
        "says": (
            "Over-privileged accounts, stale or orphaned accounts, service "
            "accounts nobody owns, MFA gaps, access review evidence for an "
            "audit."
        ),
        "triggers": ("ispm", "identity posture", "over-privileged", "access review"),
        "pairs_with": None,
    },
}

# How many areas may reach the plan. A real discovery call surfaces several,
# but injecting all eight rebuilds the burying problem select_demo_flows was
# written to solve. The classifier ranks; the cap is applied in code.
MAX_SELECTED_AREAS = 3


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
            "The highest-value file in the pack, and the one nobody else can write\n"
            "for you.\n\n"
            "**One flow per solution area, not one flow per vendor.** A vendor with\n"
            "endpoint, email, cloud workload, network, and attack-surface products\n"
            "has five flows, and which one you run depends on what discovery\n"
            "surfaced. Copy the block below once per area.\n\n"
            "Write one area first and stop. A single finished flow is worth more\n"
            "than five outlines, and you can rerun the generator immediately to see\n"
            "it used.\n\n"
            "---\n\n"
            "## <Heading in your own words, e.g. Endpoint, server, EDR or XDR>\n\n"
            "**Solution area:** exactly one of the labels in SOLUTION_AREAS.\n"
            "This is the machine-readable label; the heading above stays prose.\n"
            "A flow declaring one is selected whenever the classifier picks that\n"
            "area, whatever words the customer used to get there.\n\n"
            "**Triggered by:** comma-separated discovery signals — the words a\n"
            "customer actually says. These no longer have to be exhaustive; the\n"
            "classifier handles paraphrase, and these are the floor that fires\n"
            "regardless of what it decides. They only have to be *correct*.\n"
            "Matching is plain lowercased substring, so keep them short and\n"
            "unambiguous — a bare `soc` fires on \"social engineering\".\n"
            "*(e.g. alert fatigue, too many alerts, endpoint, EDR, triage time,\n"
            "SOC analyst, ransomware)*\n\n"
            "**Audience:** technical | executive | both  \n"
            "**Runs in:** ~N minutes\n\n"
            "### Setup\n"
            "What has to be true in the demo environment before you start. Seeded\n"
            "data, a prepared incident, a specific tenant.\n\n"
            "### Flow\n"
            "Numbered. For each step: what you show, and why it earns its place in\n"
            "*this* deal. A step you cannot justify is a step to cut.\n\n"
            "1. \n"
            "2. \n"
            "3. \n\n"
            "### The moment\n"
            "The single screen you want them discussing after you leave.\n\n"
            "### Where it goes wrong\n"
            "The failure you have actually hit, and how you recover in the room."
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


def load_pack(
    vendor: str,
    signals: list[str] | None = None,
    areas: list[str] | None = None,
) -> tuple[str, dict, list[str]]:
    """Load a vendor pack's written sections into one knowledge block.

    Skeleton sections are skipped rather than passed to the model — template
    questions in the prompt would be answered as if they were content.

    When `signals` are supplied (the opportunity's stated pains and
    environment), demo flows are narrowed to the solution areas those signals
    trigger. Returns the knowledge, the pack status, and the areas selected.
    """
    pack_dir = PACKS_DIR / vendor

    if not pack_dir.is_dir():
        raise FileNotFoundError(
            f"No vendor pack named '{vendor}'. Available: "
            f"{', '.join(available_packs()) or 'none'}"
        )

    status = pack_status(vendor)
    parts = []
    selected_areas: list[str] = []

    generic = PACKS_DIR / "generic" / "se_playbook.md"
    if generic.exists():
        parts.append(
            "# Sales Engineering Playbook (vendor-agnostic)\n\n"
            + generic.read_text(encoding="utf-8")
        )

    for filename in status["written"]:
        text = (pack_dir / filename).read_text(encoding="utf-8")

        if filename == "demo_flows.md" and (signals or areas):
            text, selected_areas = select_demo_flows(text, signals or [], areas)

        parts.append(text)

    return "\n\n---\n\n".join(parts), status, selected_areas


def parse_demo_flows(text: str) -> list[dict]:
    """Split a demo_flows.md into its per-solution-area flows.

    Each `## ` heading starts a flow. A `**Triggered by:**` line lists the
    discovery signals that make that flow the right one to run.
    """
    flows = []

    for block in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
        lines = block.splitlines()
        area = lines[0].strip()

        match = re.search(r"\*\*Triggered by:\*\*\s*(.+)", block)
        triggers = (
            [t.strip().lower() for t in match.group(1).split(",") if t.strip()]
            if match
            else []
        )

        # The machine-readable label, when the flow declares one. The heading
        # stays prose so it reads to a human; this is what the classifier's
        # output is matched against. A flow without one is still selectable by
        # its triggers, so a pack written before this keeps working.
        label = re.search(r"\*\*Solution area:\*\*\s*(.+)", block)

        flows.append(
            {
                "area": area,
                "solution_area": label.group(1).strip() if label else None,
                "triggers": triggers,
                "text": f"## {block}".rstrip(),
            }
        )

    return flows


def select_demo_flows(
    text: str, signals: list[str], areas: list[str] | None = None
) -> tuple[str, list[str]]:
    """Choose the flows whose triggers appear in the opportunity's signals.

    Injecting every flow for a multi-product vendor buries the relevant one and
    burns context on four irrelevant ones. Selection is done here in code rather
    than by asking the model to pick, for the same reason section membership is:
    a rule the code enforces holds, and a rule the prompt requests does not.

    Two mechanisms, unioned, because they fail differently:

    - `areas` are the classifier's labels. They carry recall: a customer who
      says "our field techs' laptops go weeks without checking in" never types
      a trigger phrase, and the classifier still reaches EDR/XDR.
    - `signals` are substring-matched against each flow's `**Triggered by:**`
      line. That carries the floor: an unambiguous string fires whatever the
      classifier decided, so a model having an off day cannot silently drop a
      flow the customer explicitly asked for.

    Falls back to the whole file when nothing matches, so a pack whose triggers
    are poorly chosen degrades to previous behaviour instead of going silent.
    """
    flows = parse_demo_flows(text)

    if not flows:
        return text, []

    haystack = " ".join(signals).lower()
    wanted = {area.strip().lower() for area in (areas or []) if area.strip()}

    def is_selected(flow: dict) -> bool:
        """Classifier label first, trigger floor second. Either is enough."""
        label = (flow.get("solution_area") or "").strip().lower()

        if label and label in wanted:
            return True

        return any(trigger and trigger in haystack for trigger in flow["triggers"])

    matched = [flow for flow in flows if is_selected(flow)]

    if not matched:
        return text, []

    return (
        "\n\n".join(flow["text"] for flow in matched),
        [flow["area"] for flow in matched],
    )


def load_metadata(vendor: str) -> dict:
    """Load a pack's metadata, tolerating a missing or malformed file."""
    path = PACKS_DIR / vendor / METADATA_FILE

    if not path.exists():
        return metadata_template(vendor)

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return metadata_template(vendor)
