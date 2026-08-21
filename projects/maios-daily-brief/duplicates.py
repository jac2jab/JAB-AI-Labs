"""Two-stage duplicate detection: embeddings for recall, a model for precision.

Three single-signal approaches were each measured and each hit the same wall.

    lexical overlap   catches shared vocabulary, misses the same story told in
                      different words. The Replit launch scored 0.318, below
                      the 0.35 threshold, and was missed entirely.
    embeddings        catch shared topic, but same topic is not the same event.
                      The true Grok 4.6 pair scored 0.793 while an mRNA vaccine
                      story and a robotics story scored 0.786, so no threshold
                      separates them.
    prompt-only       asking a model to rate similarity gives a number with no
                      reasoning behind it, and llama3.2 could not hold a scale.

Similarity of any single kind is not identity. So similarity is used for what it
is genuinely good at — narrowing thousands of pairs to a handful of candidates —
and the model is asked the one question it is good at: do these two texts
describe the same event, yes or no.

The model never returns a score. It returns a boolean and the merge follows from
it in code, the same rule that governs every other decision in this pipeline.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import embeddings
import relevance

# Set by classifying all 42 confirmations from a full run over 149 correctly
# split stories. Every merge at 0.83 or above was right — 15 of 15, no false
# positives. Below it precision collapses to roughly 4 correct out of 27, and
# the wrong ones are all the same mistake: the model confirming topical
# relatedness rather than event identity, justified as "both mention OpenAI",
# "all three companies released new models", "both discuss backlash against AI".
#
# The prompt lists that exact failure as a non-match and the model does it
# anyway, which is the fourth time in this project a prompt-level instruction
# has failed to hold where a code-level rule would not have.
#
# The cost is real and worth stating: this discards four merges that were
# correct, including the Techpresso/Neuron Grok 4.6 pair at 0.793 that motivated
# semantic deduplication in the first place. Showing one story twice is a
# visible error; merging two stories wrongly hides one completely.
#
# A rare-shared-entity gate was tried first and failed — all twelve test pairs
# passed it, correct and incorrect alike, because a cancer vaccine story and a
# robotics story can share rare tokens when one has absorbed the other.
CANDIDATE_THRESHOLD = 0.83

# A guard, not a tuning knob. Each candidate costs a model call of roughly 25
# seconds, so a pathological run is capped rather than left to run for hours.
# 139 stories from 28 emails produce 71 candidates out of 9,591 possible pairs,
# so this has to sit above that or real duplicates are skipped in silence.
MAX_CANDIDATES = 100

CONFIRM_SYSTEM_PROMPT = """You compare two newsletter items and decide whether
they report the SAME event.

The same event means the same announcement, launch, release, incident, report,
or acquisition. Two newsletters covering one story will emphasise different
details, quote different figures, and write entirely different sentences. That
is still the same event.

These are NOT the same event:
- two different products or models from the same company
- two unrelated stories that happen to involve the same company
- a story and a later follow-up that reports something new
- two stories that merely share a subject area, such as AI safety or robotics

Reply with JSON only."""


def _as_bool(value) -> bool:
    """Normalize the shapes a small model returns for a boolean."""
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}

    return bool(value)


def _confirm_prompt(first: dict, second: dict) -> str:
    """Build the comparison prompt for one candidate pair."""
    return (
        f"ITEM A\nNewsletter: {first.get('sender', '')}\n"
        f"Headline: {first.get('subject', '')}\n{first.get('body', '')[:900]}\n\n"
        f"ITEM B\nNewsletter: {second.get('sender', '')}\n"
        f"Headline: {second.get('subject', '')}\n{second.get('body', '')[:900]}\n\n"
        "Reply with exactly this JSON object and nothing else:\n"
        "{\n"
        '  "same_event": true or false,\n'
        '  "why": "one short sentence, at most 15 words"\n'
        "}"
    )


def confirm_same_event(first: dict, second: dict) -> tuple[bool, str]:
    """Ask the local model whether two items report the same event."""
    payload = json.dumps(
        {
            "model": relevance.OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": CONFIRM_SYSTEM_PROMPT},
                {"role": "user", "content": _confirm_prompt(first, second)},
            ],
            "stream": False,
            "format": "json",
            "options": {
                "num_predict": relevance.MAX_ANSWER_TOKENS,
                "temperature": relevance.TEMPERATURE,
                "seed": relevance.SEED,
            },
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        f"{relevance.OLLAMA_HOST}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(
            request, timeout=relevance.REQUEST_TIMEOUT_SECONDS
        ) as response:
            content = json.loads(response.read()).get("message", {}).get("content", "")

        answer = json.loads(content.strip())
    except (
        urllib.error.URLError,
        OSError,
        json.JSONDecodeError,
        TimeoutError,
    ):
        # A pair that cannot be checked is left unmerged. Failing to merge shows
        # the reader one story twice; merging wrongly hides one entirely.
        return False, "could not be checked"

    return _as_bool(answer.get("same_event")), str(answer.get("why", "")).strip()


def find_candidates(stories: list[dict], threshold: float = CANDIDATE_THRESHOLD):
    """Embed every story and return the pairs worth asking the model about."""
    vectors = [embeddings.embed_story(story) for story in stories]
    candidates = []

    for first in range(len(stories)):
        for second in range(first + 1, len(stories)):
            score = embeddings.cosine(vectors[first], vectors[second])

            if score >= threshold:
                candidates.append((score, first, second))

    candidates.sort(reverse=True)
    return candidates


def build_pair_scorer(stories: list[dict], verbose: bool = True):
    """Return a score_pair function for deduplicate(), plus what it decided.

    The returned scorer answers 1.0 for a confirmed duplicate and 0.0 otherwise,
    so deduplicate() can run at any threshold in between. The judgement is
    already made; the number only carries it across.
    """
    candidates = find_candidates(stories)
    confirmed: set[tuple[int, int]] = set()
    decisions = []

    for score, first, second in candidates[:MAX_CANDIDATES]:
        same, why = confirm_same_event(stories[first], stories[second])

        if same:
            confirmed.add((first, second))
            confirmed.add((second, first))

        decisions.append(
            {
                "cosine": round(score, 3),
                "same_event": same,
                "why": why,
                "a": stories[first].get("subject", ""),
                "b": stories[second].get("subject", ""),
                "a_sender": stories[first].get("sender", ""),
                "b_sender": stories[second].get("sender", ""),
            }
        )

        if verbose:
            print(
                "  %s cos=%.3f  %s || %s"
                % (
                    "SAME " if same else "diff ",
                    score,
                    stories[first].get("subject", "")[:34],
                    stories[second].get("subject", "")[:34],
                ),
                flush=True,
            )

    def score_pair(first: int, second: int) -> float:
        return 1.0 if (first, second) in confirmed else 0.0

    stats = {
        "candidates": len(candidates),
        "checked": len(decisions),
        "confirmed": len(confirmed) // 2,
        "decisions": decisions,
    }

    return score_pair, stats
