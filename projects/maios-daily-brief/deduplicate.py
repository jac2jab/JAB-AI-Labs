"""Near-duplicate detection for the MAIOS Daily Brief.

ROADMAP success criterion #2 is "duplicate stories are consolidated". When five
newsletters cover the same launch, the brief should report it once and say who
else carried it.

This is deliberately deterministic rather than model-based. Newsletter
duplicates share most of their content words, so token overlap catches them
reliably, runs instantly, costs nothing, and — per MAIOS Principle 2 — can
explain itself: every merge reports its similarity score and the terms the
items had in common.
"""

# Words too common to indicate that two items are about the same story.
STOPWORDS = frozenset(
    """
    a an and are as at be been but by for from has have in is it its of on or
    that the this to was were will with new news today your you we our us
    """.split()
)

# Share of content words two items must have in common to be called duplicates.
# 0.45 was chosen by running the fixture: real duplicates score well above it,
# unrelated items about the same broad topic score well below.
SIMILARITY_THRESHOLD = 0.45

MINIMUM_TOKENS = 3


def content_tokens(email: dict) -> set[str]:
    """Reduce an email to the set of content words that carry its topic."""
    text = f"{email.get('subject', '')} {email.get('body', '')}".lower()

    words = "".join(
        character if character.isalnum() or character.isspace() else " "
        for character in text
    ).split()

    return {word for word in words if word not in STOPWORDS and len(word) > 2}


def similarity(first: set[str], second: set[str]) -> float:
    """Jaccard similarity: shared terms as a share of all terms across both."""
    if not first or not second:
        return 0.0

    union = first | second

    if not union:
        return 0.0

    return len(first & second) / len(union)


def deduplicate(emails: list[dict], threshold: float = SIMILARITY_THRESHOLD) -> list[dict]:
    """Collapse near-duplicate items, keeping the highest-priority one.

    Each surviving item gains a ``duplicates`` list describing what was merged
    into it. Items with too few content words to compare are always kept.
    """
    ranked = sorted(
        enumerate(emails),
        key=lambda pair: (pair[1].get("priority", 0), -pair[0]),
        reverse=True,
    )

    token_sets = {index: content_tokens(email) for index, email in enumerate(emails)}

    merged_into_another: set[int] = set()
    survivors = []

    for index, email in ranked:
        if index in merged_into_another:
            continue

        representative = email.copy()
        representative["duplicates"] = []

        if len(token_sets[index]) < MINIMUM_TOKENS:
            survivors.append((index, representative))
            continue

        for other_index, other_email in ranked:
            if other_index == index or other_index in merged_into_another:
                continue

            if len(token_sets[other_index]) < MINIMUM_TOKENS:
                continue

            score = similarity(token_sets[index], token_sets[other_index])

            if score < threshold:
                continue

            shared = sorted(token_sets[index] & token_sets[other_index])

            representative["duplicates"].append(
                {
                    "sender": other_email.get("sender", "Unknown"),
                    "subject": other_email.get("subject", "No subject"),
                    "similarity": round(score, 2),
                    "shared_terms": shared[:6],
                }
            )
            merged_into_another.add(other_index)

        survivors.append((index, representative))

    # Restore the original input order so the brief is stable run to run.
    return [email for _, email in sorted(survivors, key=lambda pair: pair[0])]
