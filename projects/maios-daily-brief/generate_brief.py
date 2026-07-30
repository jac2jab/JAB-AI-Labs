import json
import re
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
INPUT_FILE = BASE_DIR / "data" / "sample_emails.json"
OUTPUT_DIR = BASE_DIR / "output"

MINIMUM_PRIORITY = 3


CATEGORY_KEYWORDS = {
    "Career": [
        "job",
        "jobs",
        "career",
        "recruiter",
        "solutions engineer",
        "sales engineer",
        "presales",
        "pre-sales",
        "technical evangelist",
        "interview",
    ],
    "AI Infrastructure": [
        "nvidia",
        "inference",
        "gpu",
        "data center",
        "infrastructure",
        "deployment",
        "ai factory",
    ],
    "AI News": [
        "openai",
        "anthropic",
        "agent",
        "agents",
        "enterprise ai",
        "artificial intelligence",
        "llm",
    ],
    "AI Tools": [
        "tool",
        "tools",
        "productivity",
        "app",
        "platform",
        "workflow",
    ],
}


HIGH_PRIORITY_KEYWORDS = [
    "recruiter",
    "interview",
    "application",
    "deadline",
    "urgent",
    "openai",
    "nvidia",
    "enterprise",
    "solutions engineer",
    "sales engineer",
]


LOW_PRIORITY_KEYWORDS = [
    "sale",
    "clearance",
    "discount",
    "promotion",
    "coupon",
    "today only",
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

    category_scores: dict[str, int] = {}

    for category, keywords in CATEGORY_KEYWORDS.items():
        category_scores[category] = sum(
            1 for keyword in keywords if keyword_matches(text, keyword)
        )

    best_category = max(category_scores, key=category_scores.get)

    if category_scores[best_category] == 0:
        return "General"

    return best_category


def assign_priority(email: dict) -> tuple[int, str]:
    """Assign a priority score from 1 to 5 and explain why."""
    text = combined_text(email)
    score = 3

    high_matches = [
        keyword
        for keyword in HIGH_PRIORITY_KEYWORDS
        if keyword_matches(text, keyword)
    ]

    low_matches = [
        keyword
        for keyword in LOW_PRIORITY_KEYWORDS
        if keyword_matches(text, keyword)
    ]

    score += min(len(high_matches), 2)
    score -= min(len(low_matches), 2)
    score = max(1, min(score, 5))

    reasons = []

    if high_matches:
        reasons.append(
            "High-value matches: " + ", ".join(high_matches)
        )

    if low_matches:
        reasons.append(
            "Low-value matches: " + ", ".join(low_matches)
        )

    if not reasons:
        reasons.append("No priority keywords matched")

    return score, "; ".join(reasons)


def create_summary(email: dict) -> str:
    """Use the email body as a simple first-pass summary."""
    body = email.get("body", "").strip()

    if not body:
        return "No summary available."

    return body


def enrich_emails(emails: list[dict]) -> list[dict]:
    """Add category, priority, and summary fields to each email."""
    enriched = []

    for email in emails:
        enriched_email = email.copy()
        enriched_email["category"] = assign_category(email)
        priority, priority_reason = assign_priority(email)
        enriched_email["priority"] = priority
        enriched_email["priority_reason"] = priority_reason
        enriched_email["summary"] = create_summary(email)
        enriched.append(enriched_email)

    return enriched


def select_relevant_emails(
    emails: list[dict],
    minimum_priority: int = MINIMUM_PRIORITY,
) -> list[dict]:
    """Keep relevant emails and sort them by priority."""
    selected = [
        email
        for email in emails
        if email.get("priority", 0) >= minimum_priority
    ]

    return sorted(
        selected,
        key=lambda email: email.get("priority", 0),
        reverse=True,
    )


def generate_markdown(emails: list[dict]) -> str:
    """Generate a Markdown daily brief."""
    today = datetime.now().strftime("%B %d, %Y")

    lines = [
        f"# MAIOS Daily Brief — {today}",
        "",
        "## Executive Summary",
        "",
        f"{len(emails)} relevant items require review today.",
        "",
    ]

    categories: dict[str, list[dict]] = {}

    for email in emails:
        category = email.get("category", "Uncategorized")
        categories.setdefault(category, []).append(email)

    for category, category_emails in categories.items():
        lines.append(f"## {category}")
        lines.append("")

        for email in category_emails:
            priority = email.get("priority", 0)
            subject = email.get("subject", "No subject")
            sender = email.get("sender", "Unknown sender")
            summary = email.get("summary", "No summary available")
            priority_reason = email.get(
                "priority_reason",
                "No scoring explanation available",
            )

            lines.extend(
                [
                    f"### {subject}",
                    f"**Source:** {sender}  ",
                    f"**Priority:** {priority}/5  ",
                    f"**Scoring:** {priority_reason}",
                    "",
                    summary,
                    "",
                ]
            )

    lines.extend(
        [
            "## Recommended Actions",
            "",
            "1. Review all priority-5 items.",
            "2. Identify one item relevant to JAB AI Labs.",
            "3. Review career opportunities separately.",
            "4. Ignore low-priority promotional content.",
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
        enriched_emails = enrich_emails(emails)
        selected_emails = select_relevant_emails(enriched_emails)
        brief = generate_markdown(selected_emails)
        output_file = save_brief(brief)

        print(f"Daily brief created successfully: {output_file}")

    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        print(f"Unable to generate daily brief: {error}")


if __name__ == "__main__":
    main()