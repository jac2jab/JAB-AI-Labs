"""Summarization backends for the MAIOS Daily Brief.

MAIOS Principle 1 is "private by default", so the backends are tried in that
order: a local model first, a hosted model second, and a deterministic
extractive fallback last so the program always runs for someone who has just
cloned the repository.

Every backend reports which one produced a summary, and the brief prints it.
A summary that came from the fallback is never presented as if a model wrote it.
"""

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable

# Local model (MAIOS Principle 1 — private by default).
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("MAIOS_OLLAMA_MODEL", "llama3.2")

# Hosted model, used only when no local model is available.
ANTHROPIC_MODEL = os.environ.get("MAIOS_ANTHROPIC_MODEL", "claude-opus-5")

# The first local request also loads the model into memory, which on a cold
# start can take considerably longer than the inference itself. A short timeout
# here silently degrades the whole brief to the fallback.
REQUEST_TIMEOUT_SECONDS = 180

SYSTEM_PROMPT = (
    "You summarize newsletter and email content for a single daily briefing. "
    "Reply with one sentence of at most 25 words stating what happened and why "
    "it matters. No preamble, no bullet points, no quotation marks."
)


class SummarizerUnavailable(Exception):
    """Raised by a backend that cannot serve a request right now."""


def _prompt_for(email: dict) -> str:
    """Build the user-turn prompt for a single email."""
    return (
        f"Sender: {email.get('sender', 'Unknown')}\n"
        f"Subject: {email.get('subject', 'No subject')}\n"
        f"Body: {email.get('body', '').strip()}\n\n"
        "One-sentence summary:"
    )


# --------------------------------------------------------------------------
# Backend 1 — local model via Ollama
# --------------------------------------------------------------------------

def _ollama_available() -> bool:
    """Check that Ollama is running and has at least one model pulled."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=3) as response:
            models = json.loads(response.read()).get("models", [])
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return False

    return len(models) > 0


def _summarize_with_ollama(email: dict) -> str:
    """Summarize using a locally running Ollama model."""
    payload = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _prompt_for(email)},
            ],
            "stream": False,
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
        raise SummarizerUnavailable(f"Ollama request failed: {error}") from error

    summary = body.get("message", {}).get("content", "").strip()

    if not summary:
        raise SummarizerUnavailable("Ollama returned an empty summary.")

    return summary


# --------------------------------------------------------------------------
# Backend 2 — hosted model via the Anthropic API
# --------------------------------------------------------------------------

def _anthropic_available() -> bool:
    """Check that the Anthropic SDK is installed and a key is configured."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False

    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False

    return True


def _summarize_with_anthropic(email: dict) -> str:
    """Summarize using the Anthropic API."""
    import anthropic

    client = anthropic.Anthropic()

    try:
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=150,
            system=SYSTEM_PROMPT,
            # Summarizing one short email is a small task; low effort keeps it
            # cheap and fast. Thinking stays on its default so the model does
            # not write reasoning into the visible reply.
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": _prompt_for(email)}],
        )
    except anthropic.APIError as error:
        raise SummarizerUnavailable(f"Anthropic request failed: {error}") from error

    if response.stop_reason == "refusal":
        raise SummarizerUnavailable("Anthropic declined to summarize this item.")

    summary = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()

    if not summary:
        raise SummarizerUnavailable("Anthropic returned an empty summary.")

    return summary


# --------------------------------------------------------------------------
# Backend 3 — deterministic fallback, no model
# --------------------------------------------------------------------------

def _summarize_extractively(email: dict, max_words: int = 25) -> str:
    """Return a truncated first sentence. This is not a real summary.

    The fallback exists so the program runs without a model installed. The
    brief labels output from this backend so it is never mistaken for
    model-generated text.
    """
    body = email.get("body", "").strip()

    if not body:
        return "No summary available."

    first_sentence = body.split(". ")[0].rstrip(".")
    words = first_sentence.split()

    if len(words) <= max_words:
        return f"{first_sentence}."

    return " ".join(words[:max_words]) + "..."


# --------------------------------------------------------------------------
# Backend selection
# --------------------------------------------------------------------------

def select_backend() -> tuple[str, Callable[[dict], str]]:
    """Pick the best available backend once, before summarizing anything.

    Returns a (name, function) pair. Selecting once rather than per email
    avoids re-probing a local server for every item in the brief.
    """
    if _ollama_available():
        return f"ollama:{OLLAMA_MODEL}", _summarize_with_ollama

    if _anthropic_available():
        return f"anthropic:{ANTHROPIC_MODEL}", _summarize_with_anthropic

    return "extractive-fallback", _summarize_extractively


def summarize_all(emails: list[dict]) -> tuple[list[dict], str]:
    """Attach a summary to every email. Returns the emails and the backend used.

    If a model backend fails partway through, the remaining items fall back to
    the extractive summarizer rather than aborting the whole brief.
    """
    backend_name, summarize = select_backend()
    degraded = False

    summarized = []

    for email in emails:
        item = email.copy()

        try:
            item["summary"] = summarize(email)
            item["summary_source"] = backend_name
        except SummarizerUnavailable:
            item["summary"] = _summarize_extractively(email)
            item["summary_source"] = "extractive-fallback"
            degraded = True

        summarized.append(item)

    if degraded and backend_name != "extractive-fallback":
        backend_name = f"{backend_name} (degraded — some items fell back)"

    return summarized, backend_name
