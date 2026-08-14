"""Model backends for the SE Demo Generator.

Same ordering as the MAIOS Daily Brief — local first, hosted second — because
discovery notes contain customer names, budgets, and competitive intelligence.
Sending those to a hosted API is a decision the user should make deliberately,
not one the default should make for them (MAIOS Principle 1).

There is no offline fallback here. The Daily Brief can degrade to an extractive
summary and still be useful; a demo plan generated without a model would be a
template with the customer's name pasted in, which is worse than an honest
failure.

Deliberately duplicated rather than shared with the Daily Brief. Two consumers
is not enough to justify a shared package; at a third, extract one.
"""

import json
import os
import urllib.error
import urllib.request

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("SEDG_OLLAMA_MODEL", "llama3.2")

ANTHROPIC_MODEL = os.environ.get("SEDG_ANTHROPIC_MODEL", "claude-opus-5")

# Generation is slower than summarization, the first local call also loads the
# model into memory, and a CPU-bound local model producing several hundred words
# is genuinely slow. Measured on llama3.2: roughly 4 tokens/second.
REQUEST_TIMEOUT_SECONDS = 600

# Ollama generates without limit by default. A small model given an open-ended
# prose prompt can fall into a repetition loop and never emit a stop token, so
# the request hangs until the timeout and the work is lost. Capping output
# bounds worst-case latency and costs nothing in the normal case: a section
# group that completes naturally uses around 400 tokens.
MAX_OUTPUT_TOKENS = int(os.environ.get("SEDG_MAX_OUTPUT_TOKENS", "1200"))


class ModelUnavailable(Exception):
    """Raised when no backend can serve a request."""


def _ollama_ready() -> bool:
    """Check that Ollama is running with at least one model pulled."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=3) as response:
            return len(json.loads(response.read()).get("models", [])) > 0
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return False


def _complete_ollama(system: str, user: str, json_schema: dict | None = None) -> str:
    """Run a completion against a local Ollama model.

    When a schema is supplied, this asks Ollama for JSON mode rather than
    passing the full schema. Small local models are unreliable at producing
    strict JSON on instruction alone — asking politely works most of the time,
    which is the worst failure rate to debug.

    Ollama can constrain decoding to a full JSON Schema, and that was the first
    thing tried here. On llama3.2 with this profile schema it was
    pathologically slow — a single extraction did not finish inside ten
    minutes, against roughly ninety seconds unconstrained. Plain JSON mode
    fixes the failure that was actually occurring (malformed output) at a
    fraction of that cost. The prompt still specifies the field names, and the
    caller validates the shape after parsing.
    """
    request_body = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"num_predict": MAX_OUTPUT_TOKENS},
    }

    if json_schema is not None:
        request_body["format"] = "json"

    payload = json.dumps(request_body).encode("utf-8")

    request = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError) as error:
        raise ModelUnavailable(f"Ollama request failed: {error}") from error

    text = body.get("message", {}).get("content", "").strip()

    if not text:
        raise ModelUnavailable("Ollama returned an empty response.")

    return text


def _anthropic_ready() -> bool:
    """Check that the Anthropic SDK is installed and a key is configured."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False

    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False

    return True


def _complete_anthropic(system: str, user: str, json_schema: dict | None = None) -> str:
    """Run a completion against the Anthropic API."""
    import anthropic

    client = anthropic.Anthropic()

    extra = {}
    if json_schema is not None:
        extra["output_config"] = {
            "format": {"type": "json_schema", "schema": json_schema}
        }

    try:
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
            **extra,
        )
    except anthropic.APIError as error:
        raise ModelUnavailable(f"Anthropic request failed: {error}") from error

    if response.stop_reason == "refusal":
        raise ModelUnavailable("Anthropic declined this request.")

    text = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()

    if not text:
        raise ModelUnavailable("Anthropic returned an empty response.")

    return text


def active_backend() -> str:
    """Name the backend that would serve a request right now."""
    if _ollama_ready():
        return f"ollama:{OLLAMA_MODEL}"

    if _anthropic_ready():
        return f"anthropic:{ANTHROPIC_MODEL}"

    return "none"


def complete(
    system: str, user: str, json_schema: dict | None = None
) -> tuple[str, str]:
    """Run a completion. Returns the text and the backend that produced it.

    Pass ``json_schema`` to constrain the output to that shape rather than
    hoping the model honours a formatting instruction.
    """
    if _ollama_ready():
        return _complete_ollama(system, user, json_schema), f"ollama:{OLLAMA_MODEL}"

    if _anthropic_ready():
        return (
            _complete_anthropic(system, user, json_schema),
            f"anthropic:{ANTHROPIC_MODEL}",
        )

    raise ModelUnavailable(
        "No model backend available.\n"
        "  Local  : start Ollama and run `ollama pull llama3.2`\n"
        "  Hosted : pip install anthropic, then set ANTHROPIC_API_KEY"
    )
