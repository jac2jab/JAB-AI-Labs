"""Local embeddings, used to find duplicate stories that share no vocabulary.

Lexical deduplication is exhausted, and the measurement says so rather than the
argument. Across 25 stories from six newsletters the true duplicate — Techpresso
and The Neuron both covering the Grok 4.6 launch — scored 0.250 on the overlap
coefficient, while an unrelated pair (Grok 4.6 against a humour column) scored
0.263. The true duplicate sat *below* a false one, so no threshold exists that
catches the first without merging the second.

Two write-ups of one story can share almost no words. Comparing meaning rather
than vocabulary is the only thing that reaches them.

This stays local, per MAIOS Principle 1 — the mail never leaves the machine.
Embeddings are one forward pass with no generation, so they cost seconds rather
than the minutes relevance scoring takes.
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request

OLLAMA_HOST = "http://localhost:11434"
EMBED_MODEL = "nomic-embed-text"

REQUEST_TIMEOUT_SECONDS = 60

# Embedding models have their own context limit and a long story adds little
# once the topic is established.
MAX_EMBED_CHARACTERS = 2000


class EmbeddingsUnavailable(RuntimeError):
    """Raised when no local embedding model can be reached."""


def available() -> bool:
    """True when the embedding model is pulled and Ollama is reachable."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=3) as response:
            models = json.loads(response.read()).get("models", [])
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return False

    return any(str(model.get("name", "")).startswith(EMBED_MODEL) for model in models)


def embed(text: str) -> list[float]:
    """Embed one block of text with the local model."""
    payload = json.dumps(
        {"model": EMBED_MODEL, "prompt": text[:MAX_EMBED_CHARACTERS]}
    ).encode("utf-8")

    request = urllib.request.Request(
        f"{OLLAMA_HOST}/api/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            vector = json.loads(response.read()).get("embedding", [])
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError) as error:
        raise EmbeddingsUnavailable(f"Ollama embedding request failed: {error}") from error

    if not vector:
        raise EmbeddingsUnavailable("Ollama returned an empty embedding.")

    return vector


def embed_story(story: dict) -> list[float]:
    """Embed a story from its headline and body together."""
    return embed(f"{story.get('subject', '')}\n{story.get('body', '')}")


def cosine(first: list[float], second: list[float]) -> float:
    """Cosine similarity between two vectors, clamped to 0..1."""
    if not first or not second or len(first) != len(second):
        return 0.0

    dot = sum(a * b for a, b in zip(first, second))
    magnitude = math.sqrt(sum(a * a for a in first)) * math.sqrt(sum(b * b for b in second))

    if magnitude == 0:
        return 0.0

    return max(0.0, min(dot / magnitude, 1.0))
