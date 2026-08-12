"""MAIOS Daily Brief — turn an inbox into one prioritized morning brief.

Pipeline:

    load -> categorize + score -> deduplicate -> filter -> summarize -> render

Each stage reports how many items it removed, so the ROADMAP's "reduce daily
reading time by at least 80%" target is measured rather than assumed.
"""

import json
import re
from datetime import datetime
from pathlib import Path

from deduplicate import deduplicate
from summarizer import summarize_all

BASE_DIR = Path(__file__).resolve().parent
INPUT_FILE = BASE_DIR / "data" / "sample_emails.json"
OUTPUT_DIR = BASE_DIR / "output"

# An item must score above the neutral baseline to earn a place in the brief.
# v0.2 set this to 3 — the same value every item starts at — so anything that
# matched no keyword passed by default and the filter removed almost nothing.
BASELINE_PRIORITY = 3
MINIMUM_PRIORITY = 4


CATEGORY_KEYWORDS = {
    "Career": [
        "job", "jobs", "career", "recruiter", "solutions engineer",
        "sales engineer", "presales", "pre-sales", "technical evangelist",
        "interview", "application", "hiring",
    ],
    "AI Infrastructure": [
        "nvidia", "inference", "gpu", "data center", "infrastructure",
        "deployment", "ai factory", "vector database", "embedding",
    ],
    "AI News": [
        "openai", "anthropic", "agent", "agents", "enterprise ai",
        "artificial intelligence", "llm", "claude", "orchestration",
    ],
    "AI Tools": [
        "tool", "tools", "productivity", "app", "platform", "workflow",
    ],
}


HIGH_PRIORITY_KEYWORDS = [
    "recruiter", "interview", "application", "deadline", "urgent",
    "openai", "nvidia", "anthropic", "enterprise",
    "solutions engineer", "sales engineer", "technical evangelist",
]


LOW_PRIORITY_KEYWORDS = [
    "sale", "clearance", "discount", "promotion", "coupon", "today only",
    "flash sale", "early bird", "limited time",
]


def load_emails(file_path: Path) -> list[dict]:
    """Load email records from a JSON file."""
    if not file_path.exists():
        raise FileNotFoundError(f"Input file not found: {file_path}")

    with file_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError("Email data must be a JSON list.")

    return data


def combined_text(email: dict) -> str:
    """Combine email fields into one lowercase string for analysis."""
    sender = email.get("sender", "")
    subject = email.get("subject", "")
    body = email.get("body", "")

    return f"{sender} {subject} {body}".lower()


def keyword_matches(text: str, keyword: str) -> bool:
    """Match complete words or phrases instead of partial words."""
    pattern = rf"\b{re.escape(keyword)}\b"
    return re.search(pattern, text) is not None


def assign_category(email: dict) -> str:
    """Assign a category based on matching keywords."""
    text = combined_text(email)

    category_scores = {
        category: sum(1 for keyword in keywords if keyword_matches(text, keyword))
        for category, keywords in CATEGORY_KEYWORDS.items()
    }

    best_category = max(category_scores, key=category_scores.get)

    if category_scores[best_category] == 0:
        return "General"

    return best_category


def assign_priority(email: dict) -> tuple[int, str]:
    """Assign a priority score from 1 to 5 and explain why."""
    text = combined_text(email)
    score = BASELINE_PRIORITY

    high_matches = [k for k in HIGH_PRIORITY_KEYWORDS if keyword_matches(text, k)]
    low_matches = [k for k in LOW_PRIORITY_KEYWORDS if keyword_matches(text, k)]

    score += min(len(high_matches), 2)
    score -= min(len(low_matches), 2)
    score = max(1, min(score, 5))

    reasons = []

    if high_matches:
        reasons.append("High-value matches: " + ", ".join(high_matches))

    if low_matches:
        reasons.append("Low-value matches: " + ", ".join(low_matches))

    if not reasons:
        reasons.append("No priority keywords matched")

    return score, "; ".join(reasons)


def enrich_emails(emails: list[dict]) -> list[dict]:
    """Add category and priority fields to each email."""
    enriched = []

    for email in emails:
        item = email.copy()
        item["category"] = assign_category(email)
        priority, reason = assign_priority(email)
        item["priority"] = priority
        item["priority_reason"] = reason
        enriched.append(item)

    return enriched


def select_relevant_emails(
    emails: list[dict],
    minimum_priority: int = MINIMUM_PRIORITY,
) -> list[dict]:
    """Keep items above the relevance floor and sort them by priority."""
    selected = [e for e in emails if e.get("priority", 0) >= minimum_priority]

    return sorted(selected, key=lambda e: e.get("priority", 0), reverse=True)


def generate_markdown(emails: list[dict], metrics: dict, backend: str) -> str:
    """Generate the Markdown daily brief."""
    today = datetime.now().strftime("%B %d, %Y")

    lines = [
        f"# MAIOS Daily Brief — {today}",
        "",
        "## Executive Summary",
        "",
        f"{metrics['final']} of {metrics['input']} items need review today "
        f"— a {metrics['reduction_percent']}% reduction.",
        "",
        f"- {metrics['duplicates_merged']} duplicate "
        f"{'story' if metrics['duplicates_merged'] == 1 else 'stories'} consolidated",
        f"- {metrics['filtered_out']} items below the relevance floor "
        f"(priority < {MINIMUM_PRIORITY})",
        f"- Summaries generated by `{backend}`",
        "",
    ]

    categories: dict[str, list[dict]] = {}

    for email in emails:
        categories.setdefault(email.get("category", "Uncategorized"), []).append(email)

    for category, category_emails in categories.items():
        lines.append(f"## {category}")
        lines.append("")

        for email in category_emails:
            lines.extend(
                [
                    f"### {email.get('subject', 'No subject')}",
                    f"**Source:** {email.get('sender', 'Unknown sender')}  ",
                    f"**Priority:** {email.get('priority', 0)}/5  ",
                    f"**Scoring:** {email.get('priority_reason', 'n/a')}",
                    "",
                    email.get("summary", "No summary available."),
                    "",
                ]
            )

            duplicates = email.get("duplicates", [])

            if duplicates:
                lines.append(
                    f"*Also covered by {len(duplicates)} other "
                    f"{'source' if len(duplicates) == 1 else 'sources'}:*"
                )
                for duplicate in duplicates:
                    lines.append(
                        f"- {duplicate['sender']} — "
                        f"similarity {duplicate['similarity']}, "
                        f"shared terms: {', '.join(duplicate['shared_terms'])}"
                    )
                lines.append("")

    lines.extend(
        [
            "## Recommended Actions",
            "",
            "1. Review all priority-5 items.",
            "2. Identify one item relevant to JAB AI Labs.",
            "3. Review career opportunities separately.",
            "",
        ]
    )

    return "\n".join(lines)


def save_brief(content: str) -> Path:
    """Save the daily brief to the output directory."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    date_string = datetime.now().strftime("%Y-%m-%d")
    output_file = OUTPUT_DIR / f"daily_brief_{date_string}.md"

    output_file.write_text(content, encoding="utf-8")
    return output_file


def main() -> None:
    try:
        emails = load_emails(INPUT_FILE)
        enriched = enrich_emails(emails)

        deduplicated = deduplicate(enriched)
        duplicates_merged = len(enriched) - len(deduplicated)

        selected = select_relevant_emails(deduplicated)
        filtered_out = len(deduplicated) - len(selected)

        summarized, backend = summarize_all(selected)

        metrics = {
            "input": len(emails),
            "duplicates_merged": duplicates_merged,
            "filtered_out": filtered_out,
            "final": len(summarized),
            "reduction_percent": (
                round(100 * (len(emails) - len(summarized)) / len(emails))
                if emails
                else 0
            ),
        }

        brief = generate_markdown(summarized, metrics, backend)
        output_file = save_brief(brief)

        print(f"Items in:            {metrics['input']}")
        print(f"Duplicates merged:  -{metrics['duplicates_merged']}")
        print(f"Below relevance:    -{metrics['filtered_out']}")
        print(f"Items out:           {metrics['final']}")
        print(f"Reduction:           {metrics['reduction_percent']}%  (target: 80%)")
        print(f"Summarizer:          {backend}")
        print(f"Brief written to:    {output_file}")

    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        print(f"Unable to generate daily brief: {error}")


if __name__ == "__main__":
    main()
