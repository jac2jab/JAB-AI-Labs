"""MAIOS Daily Brief — turn an inbox into one prioritized morning brief.

Pipeline:

    load -> split -> categorize + score -> deduplicate -> filter -> summarize
    -> render

Each stage reports how many items it removed, so the ROADMAP's "reduce daily
reading time by at least 80%" target is measured rather than assumed.
"""

import argparse
import json
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import relevance
from deduplicate import deduplicate
from ingest import load_emails
from stories import split_all
from summarizer import summarize_all

BASE_DIR = Path(__file__).resolve().parent
INPUT_FILE = BASE_DIR / "data" / "sample_emails.json"
OUTPUT_DIR = BASE_DIR / "output"

# An item must score above the neutral baseline to earn a place in the brief.
# v0.2 set this to 3 — the same value every item starts at — so anything that
# matched no keyword passed by default and the filter removed almost nothing.
BASELINE_PRIORITY = 3
MINIMUM_PRIORITY = 4

# A roundup carries six to eight stories and three or four of them are worth
# reading. Capping per issue also stops one prolific newsletter from filling a
# brief assembled from ten of them.
MAX_ITEMS_PER_ISSUE = 4


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


def select_scorer() -> tuple[Callable[[dict], tuple[int, str]], str]:
    """Choose the relevance scorer, preferring the local model.

    Keyword scoring stays as the fallback rather than being deleted. It is also
    the baseline compare_scoring.py measures against, so it has to keep working.
    """
    if relevance.available():
        return relevance.score_story, f"ollama:{relevance.OLLAMA_MODEL}"

    return assign_priority, "keyword matching (no local model available)"


def enrich_emails(
    emails: list[dict],
    scorer: Callable[[dict], tuple[int, str]] = assign_priority,
) -> tuple[list[dict], int]:
    """Add category and priority fields to each item.

    Returns the enriched items and how many fell back to keyword scoring, so a
    partly-degraded brief can say so rather than looking wholly model-scored.
    """
    enriched = []
    fell_back = 0

    for index, email in enumerate(emails, start=1):
        item = email.copy()
        item["category"] = assign_category(email)

        try:
            priority, reason = scorer(email)
        except relevance.RelevanceUnavailable as error:
            # One story failing must not discard a run that is minutes long,
            # but the brief has to report that this item was scored differently.
            priority, reason = assign_priority(email)
            reason = f"keyword fallback ({error}) — {reason}"
            fell_back += 1

        item["priority"] = priority
        item["priority_reason"] = reason
        enriched.append(item)

        print(
            f"  scored [{index}/{len(emails)}] {priority}/5  "
            f"{email.get('subject', '')[:52]}",
            flush=True,
        )

    return enriched, fell_back


def cap_per_issue(items: list[dict], limit: int) -> list[dict]:
    """Keep only the highest-scoring stories from each newsletter issue.

    A relevance floor treats every newsletter as one pool, so a single issue
    with eight strong stories can crowd out every other sender. Capping per
    issue keeps the brief representative of the morning's mail rather than of
    whichever newsletter wrote the most that day.
    """
    if limit <= 0:
        return items

    kept: list[dict] = []
    per_issue: dict[str, int] = {}

    for item in sorted(items, key=lambda i: -i.get("priority", 0)):
        issue = item.get("parent_subject") or item.get("sender", "")

        if per_issue.get(issue, 0) >= limit:
            continue

        per_issue[issue] = per_issue.get(issue, 0) + 1
        kept.append(item)

    return kept


def select_relevant_emails(
    emails: list[dict],
    minimum_priority: int = MINIMUM_PRIORITY,
) -> list[dict]:
    """Keep items above the relevance floor and sort them by priority."""
    selected = [e for e in emails if e.get("priority", 0) >= minimum_priority]

    return sorted(selected, key=lambda e: e.get("priority", 0), reverse=True)


def generate_markdown(
    emails: list[dict],
    metrics: dict,
    backend: str,
    source: str,
    scorer_label: str = "keyword matching",
) -> str:
    """Generate the Markdown daily brief."""
    today = datetime.now().strftime("%B %d, %Y")

    lines = [
        f"# MAIOS Daily Brief — {today}",
        "",
        "## Executive Summary",
        "",
        f"{metrics['final']} of {metrics['input']} items need review today "
        f"— a {metrics['reduction_percent']}% reduction in items, and "
        f"{metrics['words_saved_percent']}% fewer words to read.",
        "",
        f"- {metrics['duplicates_merged']} duplicate "
        f"{'story' if metrics['duplicates_merged'] == 1 else 'stories'} consolidated",
        f"- {metrics['filtered_out']} items below the relevance floor "
        f"(priority < {MINIMUM_PRIORITY})",
        f"- {metrics['capped_out']} items beyond the top "
        f"{metrics['per_issue']} of their issue",
        f"- {metrics['input_words']:,} words in → {metrics['output_words']:,} words out",
        f"- Source: {source}",
        f"- Relevance scored by `{scorer_label}`",
        f"- Summaries generated by `{backend}`",
        "",
    ]

    if metrics.get("scored_by_fallback"):
        lines.insert(
            -1,
            f"- **{metrics['scored_by_fallback']} items fell back to keyword "
            "scoring** and are not model-scored",
        )

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


def save_brief(content: str, source: Path) -> Path:
    """Save the daily brief, named by date and source.

    The source belongs in the filename because two runs on the same day from
    different inboxes are two different briefs. Naming by date alone let a
    fixture run silently overwrite a real-mail one.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    slug = re.sub(r"[^a-z0-9]+", "-", source.stem.lower()).strip("-") or "inbox"
    date_string = datetime.now().strftime("%Y-%m-%d")
    output_file = OUTPUT_DIR / f"daily_brief_{date_string}_{slug}.md"

    output_file.write_text(content, encoding="utf-8")
    return output_file


def word_count(text: str) -> int:
    """Count words in a block of text."""
    return len(text.split())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Turn an inbox into one prioritized morning brief."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=INPUT_FILE,
        help=(
            "A .json fixture, a .eml file, a directory of .eml files, or a "
            f".mbox archive. Defaults to {INPUT_FILE.name}."
        ),
    )
    parser.add_argument(
        "--per-issue",
        type=int,
        default=MAX_ITEMS_PER_ISSUE,
        help=(
            "Keep at most this many stories from each newsletter issue. "
            f"Defaults to {MAX_ITEMS_PER_ISSUE}; 0 disables the cap."
        ),
    )
    args = parser.parse_args()

    try:
        emails, source_label = load_emails(args.source)

        if not emails:
            print(f"No email records found in {args.source}")
            return

        # The baseline is the whole newsletter as it arrived, measured before
        # anything is split or dropped. That is what a person would have had to
        # read. v0.4.1 measured the truncated 4,000-character body instead,
        # which understated the input by 58%.
        input_words = sum(word_count(e.get("body", "")) for e in emails)

        # A roundup is not one item. Split first so relevance and summarization
        # both operate on a single story's own text.
        items = split_all(emails)

        scorer, scorer_label = select_scorer()
        print(f"Scoring {len(items)} stories with {scorer_label}...", flush=True)
        enriched, scored_by_fallback = enrich_emails(items, scorer)

        deduplicated = deduplicate(enriched)
        duplicates_merged = len(enriched) - len(deduplicated)

        above_floor = select_relevant_emails(deduplicated)
        filtered_out = len(deduplicated) - len(above_floor)

        selected = cap_per_issue(above_floor, args.per_issue)
        capped_out = len(above_floor) - len(selected)

        summarized, backend = summarize_all(selected)

        output_words = sum(word_count(e.get("summary", "")) for e in summarized)

        metrics = {
            "emails": len(emails),
            "input": len(items),
            "duplicates_merged": duplicates_merged,
            "filtered_out": filtered_out,
            "final": len(summarized),
            "reduction_percent": round(
                100 * (len(items) - len(summarized)) / len(items)
            ),
            "input_words": input_words,
            "output_words": output_words,
            "scored_by_fallback": scored_by_fallback,
            "capped_out": capped_out,
            "per_issue": args.per_issue,
            "words_saved_percent": (
                round(100 * (input_words - output_words) / input_words)
                if input_words
                else 0
            ),
        }

        brief = generate_markdown(
            summarized, metrics, backend, source_label, scorer_label
        )
        output_file = save_brief(brief, args.source)

        print(f"Source:              {source_label}")
        print(f"Emails in:           {metrics['emails']}")
        print(f"Stories after split: {metrics['input']}")
        print(f"Duplicates merged:  -{metrics['duplicates_merged']}")
        print(f"Below relevance:    -{metrics['filtered_out']}")
        print(f"Beyond top {args.per_issue}/issue:  -{metrics['capped_out']}")
        print(f"Items out:           {metrics['final']}")
        print(f"Item reduction:      {metrics['reduction_percent']}%")
        print(
            f"Words to read:       {metrics['input_words']:,} -> "
            f"{metrics['output_words']:,}"
        )
        print(
            f"Reading reduction:   {metrics['words_saved_percent']}%  (target: 80%)"
        )
        print(f"Relevance scorer:    {scorer_label}")

        if scored_by_fallback:
            print(f"  fell back to keywords for {scored_by_fallback} items")

        print(f"Summarizer:          {backend}")
        print(f"Brief written to:    {output_file}")

    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        print(f"Unable to generate daily brief: {error}")


if __name__ == "__main__":
    main()
