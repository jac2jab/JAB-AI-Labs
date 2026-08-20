"""Model-assisted relevance scoring for a single story.

v0.4.1 scored relevance by keyword. That failed twice over: a hand-kept
vocabulary cannot track a field that names a new model monthly, and one keyword
anywhere scored an entire roundup. Splitting fixed the second; this fixes the
first.

Three things are enforced here rather than asked for, each after watching the
model fail at them:

1. The model never emits a score. Small models do not hold a calibrated 1-5
   scale. It picks a category; the arithmetic lives in code, in one place.

2. The model is not asked whether an item is newsletter furniture. Asked as an
   independent yes/no alongside the relevance questions, its answers moved
   together - one framing made everything furniture and nothing relevant, the
   next made everything relevant and nothing furniture. Link density separates
   list roundups from stories cleanly on the real sample, so code does it.

3. The question is a forced single choice, not independent booleans. Given
   yes/no questions llama3.2 answered yes to all of them, including a WhatsApp
   consumer feature and a publisher licensing deal. Made to pick one label, it
   has to discriminate.

The categories come from Jason's own statement of relevance: an item matters
when it changes what he would build, or what he would say to a customer.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# Overridable so a larger model can be measured against the same stories
# without editing code. llama3.2 is 3B and its judgment is visibly unsteady:
# it classified the same Grok 4.6 launch as a 5/5 capability from one
# newsletter and 2/5 business news from another.
OLLAMA_MODEL = os.environ.get("MAIOS_RELEVANCE_MODEL", "llama3.2")

MAX_ANSWER_TOKENS = 200
REQUEST_TIMEOUT_SECONDS = 180

# temperature 0 alone is NOT reproducible here. Two identical runs over the same
# 25 stories disagreed on two of them - "Grok takes on OpenAI in coding" and
# "SpaceXAI launches Grok Bot" scored 5/5 in one run and below the floor in the
# next - because Ollama seeds each request randomly unless told otherwise. A
# fixed seed is what actually makes a rerun comparable, and every measurement
# in this project depends on that.
TEMPERATURE = 0
SEED = 42

# Measured across the 36 stories from six real newsletters: every link roundup
# and tools list carried 5 or more bracketed links, and the highest a real
# story reached was 4 (Grok 4.6, whose "here is what happened" section is a
# short bulleted list). No false positives on this sample; a wider one will
# move it.
LIST_LINK_THRESHOLD = 5
LINK_RE = re.compile(r"\[[^\]]{3,60}\]")

# What each category is worth. Kept as data so the weighting is visible and
# changeable without touching the prompt.
CATEGORY_SCORES = {
    "new_or_changed_capability": 5,
    "security_or_privacy_development": 4,
    "business_or_industry_news": 2,
    "consumer_product_news": 2,
    "list_of_links_or_tools": 1,
}

CATEGORY_MEANING = {
    "new_or_changed_capability": "changes what I would build",
    "security_or_privacy_development": "changes what I would say to a customer",
    "business_or_industry_news": "industry news - changes neither",
    "consumer_product_news": "consumer product news - changes neither",
    "list_of_links_or_tools": "newsletter furniture",
}

UNKNOWN_CATEGORY_SCORE = 3

SYSTEM_PROMPT = """You classify technology news for one specific person.

That person is a customer-facing solutions engineer with 30 years in enterprise
technology - endpoint and network security - who is now building applied AI
systems hands-on.

Pick the ONE category that best describes the story. Judge the story by what it
reports, not by whether it mentions him.

new_or_changed_capability
    A model, tool, technique, price, benchmark, context limit, or failure mode
    that someone designing or running an AI system would weigh when deciding
    what to use or how to build it.

security_or_privacy_development
    A vulnerability, breach, attack technique, malware, or a change in how a
    product actually handles data, that would alter his technical advice to a
    customer about risk. The story has to describe a technical threat or a
    technical safeguard.

business_or_industry_news
    Funding, valuations, executive moves, lawsuits, court rulings, antitrust
    and regulatory decisions, partnerships, licensing deals, market share, or
    user counts.

    A story about what a company is required to do by a court or a regulator,
    or about who has agreed to work with whom, belongs here even when its
    subject matter touches security or privacy.

consumer_product_news
    A feature for ordinary consumers with no bearing on how enterprise AI
    systems get designed or sold.

list_of_links_or_tools
    A roundup of unrelated links, a list of tools, or a housekeeping note
    rather than a single news story.

Exactly one category. Reply with JSON only."""


class RelevanceUnavailable(RuntimeError):
    """Raised when no local model can score, so the caller can say so."""


def is_list_roundup(story: dict) -> bool:
    """True when a story is a link roundup, decided structurally, not asked."""
    return len(LINK_RE.findall(story.get("body", ""))) >= LIST_LINK_THRESHOLD


def _prompt_for(story: dict) -> str:
    """Build the classification prompt for one story."""
    categories = ", ".join(CATEGORY_SCORES)

    return (
        f"Newsletter: {story.get('sender', '')}\n"
        f"Headline: {story.get('subject', '')}\n"
        f"Story:\n{story.get('body', '')}\n"
        "\n"
        "Reply with exactly this JSON object and nothing else:\n"
        "{\n"
        f'  "category": "one of: {categories}",\n'
        '  "why": "one short sentence, at most 20 words"\n'
        "}"
    )


def _ask_ollama(story: dict) -> dict:
    """Ask the local model to classify one story."""
    payload = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _prompt_for(story)},
            ],
            "stream": False,
            # JSON mode, not schema-constrained decoding. The full schema was
            # pathologically slow on llama3.2 in the SE generator; JSON mode
            # fixes the failure that actually occurs, malformed output.
            "format": "json",
            "options": {
                "num_predict": MAX_ANSWER_TOKENS,
                "temperature": TEMPERATURE,
                "seed": SEED,
            },
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError) as error:
        raise RelevanceUnavailable(f"Ollama request failed: {error}") from error

    content = body.get("message", {}).get("content", "").strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError as error:
        raise RelevanceUnavailable(
            f"Model did not return JSON: {content[:120]!r}"
        ) from error


def score_from_answer(answer: dict, roundup: bool = False) -> tuple[int, str]:
    """Turn one classification into a 1-5 score. The arithmetic lives here.

    A story the code has already identified as a link roundup is scored as one
    whatever the model said, because the structural signal is the reliable one.
    """
    category = str(answer.get("category", "")).strip().lower()

    if roundup:
        category = "list_of_links_or_tools"

    score = CATEGORY_SCORES.get(category, UNKNOWN_CATEGORY_SCORE)
    meaning = CATEGORY_MEANING.get(category, f"unrecognized category {category!r}")

    reason = f"{meaning} [{category or 'none'}]"

    if roundup:
        return score, f"{reason} - 5 or more links, classified structurally"

    why = str(answer.get("why", "")).strip()

    if why:
        reason = f"{reason} - {why}"

    return score, reason


def score_story(story: dict) -> tuple[int, str]:
    """Score one story: structure first, then the model."""
    if is_list_roundup(story):
        # No model call needed; the structure already decided it.
        return score_from_answer({}, roundup=True)

    return score_from_answer(_ask_ollama(story))


def available() -> bool:
    """Check that Ollama is running and has a model pulled."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=3) as response:
            return len(json.loads(response.read()).get("models", [])) > 0
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return False
