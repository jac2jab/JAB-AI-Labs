import json
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
INPUT_FILE = BASE_DIR / "data" / "sample_emails.json"
OUTPUT_DIR = BASE_DIR / "output"

MINIMUM_PRIORITY = 3


def load_emails(file_path: Path) -> list[dict]:
    """Load email records from a JSON file."""
    if not file_path.exists():
        raise FileNotFoundError(f"Input file not found: {file_path}")

    with file_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError("Email data must be a JSON list.")

    return data


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

            lines.extend(
                [
                    f"### {subject}",
                    f"**Source:** {sender}  ",
                    f"**Priority:** {priority}/5",
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
        selected_emails = select_relevant_emails(emails)
        brief = generate_markdown(selected_emails)
        output_file = save_brief(brief)

        print(f"Daily brief created successfully: {output_file}")

    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        print(f"Unable to generate daily brief: {error}")


if __name__ == "__main__":
    main()
