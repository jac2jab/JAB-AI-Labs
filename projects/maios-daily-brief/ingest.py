"""Email ingestion for the MAIOS Daily Brief.

Reads real mail without needing an account password, an OAuth consent screen,
or a network connection: point it at `.eml` files, a `.mbox` archive, or the
JSON fixture and it normalizes all three into the same record shape.

That choice is MAIOS Principle 1 — private by default. Mail is read from disk,
summarized by a local model, and never leaves the machine.

Exporting mail to feed it:
  - Gmail: open a message, ⋮ menu, "Download message" -> a .eml file
  - Gmail bulk: takeout.google.com -> Mail -> a .mbox archive
  - Outlook / Apple Mail: drag messages to a folder -> .eml files
"""

import email
import email.policy
import json
import mailbox
import re
from pathlib import Path

# Keep whole newsletters out of the model prompt; the opening is enough to
# summarize from and bounds both latency and memory.
MAX_BODY_CHARACTERS = 4000


def _strip_html(html: str) -> str:
    """Reduce an HTML body to readable text.

    Deliberately crude — no dependency, and the summarizer only needs prose,
    not structure.
    """
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)

    replacements = {
        "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&quot;": '"', "&#39;": "'", "&mdash;": "—", "&ndash;": "–",
    }
    for entity, character in replacements.items():
        text = text.replace(entity, character)

    return text


def _clean(text: str) -> str:
    """Collapse whitespace and trim to a workable length."""
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    text = text.strip()

    if len(text) <= MAX_BODY_CHARACTERS:
        return text

    return text[:MAX_BODY_CHARACTERS].rsplit(" ", 1)[0] + "..."


def _body_of(message: email.message.Message) -> str:
    """Extract readable text from a message, preferring plain text over HTML."""
    if not message.is_multipart():
        content = message.get_content() if hasattr(message, "get_content") else ""
        if message.get_content_type() == "text/html":
            content = _strip_html(str(content))
        return _clean(str(content))

    plain_parts, html_parts = [], []

    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_filename():  # skip attachments
            continue

        try:
            content = str(part.get_content())
        except (LookupError, ValueError):
            continue

        if part.get_content_type() == "text/plain":
            plain_parts.append(content)
        elif part.get_content_type() == "text/html":
            html_parts.append(content)

    if plain_parts:
        return _clean("\n".join(plain_parts))

    return _clean(_strip_html("\n".join(html_parts)))


def _record_from(message: email.message.Message) -> dict:
    """Normalize a parsed message into the record shape the pipeline expects."""
    sender = str(message.get("From", "Unknown sender"))

    # "The Neuron <hi@theneuron.ai>" -> "The Neuron"
    display_name = re.match(r'^\s*"?([^"<]+?)"?\s*<', sender)
    if display_name:
        sender = display_name.group(1).strip()

    return {
        "sender": sender,
        "subject": str(message.get("Subject", "No subject")),
        "date": str(message.get("Date", "")),
        "body": _body_of(message),
    }


def _load_eml(path: Path) -> list[dict]:
    """Load a single .eml file."""
    with path.open("rb") as file:
        message = email.message_from_binary_file(file, policy=email.policy.default)

    return [_record_from(message)]


def _load_mbox(path: Path) -> list[dict]:
    """Load every message in a .mbox archive."""
    archive = mailbox.mbox(str(path), factory=None)

    records = []
    for raw in archive:
        message = email.message_from_string(str(raw), policy=email.policy.default)
        records.append(_record_from(message))

    return records


def _load_json(path: Path) -> list[dict]:
    """Load the JSON fixture."""
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError("Email data must be a JSON list.")

    return data


def load_emails(source: Path) -> tuple[list[dict], str]:
    """Load email records from a file or directory.

    Accepts a .json fixture, a single .eml, a directory of .eml files, or a
    .mbox archive. Returns the records and a label naming what was read, so the
    brief can state its own provenance.
    """
    source = Path(source)

    if not source.exists():
        raise FileNotFoundError(f"Source not found: {source}")

    if source.is_dir():
        files = sorted(source.glob("*.eml"))

        if not files:
            raise ValueError(f"No .eml files found in {source}")

        records = [record for file in files for record in _load_eml(file)]
        return records, f"{len(files)} .eml files from {source.name}/"

    suffix = source.suffix.lower()

    if suffix == ".json":
        return _load_json(source), f"JSON fixture ({source.name})"

    if suffix == ".eml":
        return _load_eml(source), f".eml file ({source.name})"

    if suffix == ".mbox":
        records = _load_mbox(source)
        return records, f".mbox archive ({source.name}, {len(records)} messages)"

    raise ValueError(
        f"Unsupported source type '{suffix}'. Use .json, .eml, .mbox, "
        "or a directory of .eml files."
    )
