"""Score every story both ways and print the disagreements.

v0.5 replaces keyword relevance with a model. The claim that it is better has
to be measurable, not asserted, so this runs both scorers over the same stories
and shows where they differ and what each would have put in the brief.

    python compare_scoring.py --source "path/to/newsletters"
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import generate_brief as gb
import relevance
from ingest import load_emails
from stories import split_all

MINIMUM_PRIORITY = gb.MINIMUM_PRIORITY


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()

    emails, label = load_emails(args.source)
    items = split_all(emails)

    print(f"Source: {label}")
    print(f"Emails: {len(emails)} -> stories: {len(items)}")
    print(f"Relevance floor: {MINIMUM_PRIORITY}\n")

    rows = []
    started = time.time()

    for index, story in enumerate(items, start=1):
        keyword_score, keyword_reason = gb.assign_priority(story)

        try:
            model_score, model_reason = relevance.score_story(story)
        except relevance.RelevanceUnavailable as error:
            model_score, model_reason = None, f"UNAVAILABLE: {error}"

        rows.append((story, keyword_score, keyword_reason, model_score, model_reason))
        print(f"  [{index}/{len(items)}] {story['subject'][:60]}", flush=True)

    elapsed = time.time() - started

    print(f"\nScored {len(rows)} stories in {elapsed:.0f}s\n")
    print("=" * 100)
    print("DISAGREEMENTS (one scorer keeps it, the other drops it)")
    print("=" * 100)

    for story, keyword_score, keyword_reason, model_score, model_reason in rows:
        if model_score is None:
            continue

        keyword_keeps = keyword_score >= MINIMUM_PRIORITY
        model_keeps = model_score >= MINIMUM_PRIORITY

        if keyword_keeps == model_keeps:
            continue

        verdict = "MODEL KEEPS, keyword drops" if model_keeps else "KEYWORD KEEPS, model drops"
        print(f"\n{verdict}: {story['subject'][:70]}")
        print(f"    keyword {keyword_score}/5  {keyword_reason[:80]}")
        print(f"    model   {model_score}/5  {model_reason[:80]}")

    print("\n" + "=" * 100)
    print("WHAT EACH SCORER WOULD PUT IN THE BRIEF")
    print("=" * 100)

    for name, index in (("KEYWORD", 1), ("MODEL", 3)):
        kept = [row for row in rows if row[index] is not None and row[index] >= MINIMUM_PRIORITY]
        print(f"\n{name}: {len(kept)} of {len(rows)} stories")

        for row in sorted(kept, key=lambda r: -r[index]):
            print(f"    {row[index]}/5  {row[0]['subject'][:66]}")


if __name__ == "__main__":
    main()
