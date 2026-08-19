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
import html
import json
import mailbox
import re
from pathlib import Path

# The email body is no longer truncated. Capping it at 4,000 characters
# discarded 58% of every roundup (5,298 of 9,201 words across the six real
# newsletters), and in one case discarded the story named in the subject line
# while keeping its table-of-contents entry — so the summarizer wrote about a
# headline it had no article for. Bounding the model prompt is now stories.py's
# job, which caps each story separately once the email has been split.
MAX_BODY_CHARACTERS = None

# Newsletters pad the inbox preview snippet with hundreds of invisible
# characters. Unescaped they are silent; escaped as &#8204; they flood the
# extracted text and consume the character budget before any real content.
INVISIBLE_CHARACTERS = dict.fromkeys(
    map(ord, "​‌‍⁠﻿­"), None
)

# A text/plain part shorter than this is treated as a stub rather than the
# article, and the HTML part is used instead if it carries more.
STUB_BODY_CHARACTERS = 600


def _strip_html(markup: str) -> str:
    """Reduce an HTML body to readable text.

    Deliberately crude — no dependency, and the summarizer needs prose, not
    structure. Entity decoding is delegated to the standard library rather than
    a hand-written table: real newsletters use numeric entities heavily, and a
    table that only knows `&nbsp;` leaves `&#160;` and `&#8204;` intact.
    """
    text = re.sub(r"(?is)<(script|style|head).*?>.*?</\1>", " ", markup)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h[1-6]>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)

    return html.unescape(text)


def _clean(text: str) -> str:
    """Strip newsletter furniture, collapse whitespace, and bound the length."""
    text = text.translate(INVISIBLE_CHARACTERS)
    text = text.replace(" ", " ")

    # URLs carry no meaning for a summarizer and are long enough to crowd out
    # the article itself — one tracking link can run past 200 characters.
    text = re.sub(r"\(?\bhttps?://\S+\)?", " ", text)

    # Image and link placeholders left behind by HTML-to-text conversion.
    text = re.sub(r"(?im)^\s*(view image|image)\s*:\s*$", " ", text)
    text = re.sub(r"(?i)\bview image\b\s*:?", " ", text)

    # Rules made of repeated punctuation, used as section dividers.
    text = re.sub(r"(?m)^\s*[-–—=_*·•]{3,}\s*$", "\n", text)

    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", text)
    text = text.strip()

    if MAX_BODY_CHARACTERS is None or len(text) <= MAX_BODY_CHARACTERS:
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

    plain = _clean("\n".join(plain_parts)) if plain_parts else ""
    from_html = _clean(_strip_html("\n".join(html_parts))) if html_parts else ""

    # Plain text is preferred when it is real. Many newsletters ship a stub
    # instead — "You are reading a plain text version of this post, view it
    # online at..." — where the article lives only in the HTML part. Measured
    # on real Techpresso mail: a 210-character stub beside 102KB of HTML.
    # Falling back only when plain text is absent silently discards the entire
    # newsletter, so compare the two and take the one carrying content.
    if plain and (len(plain) >= STUB_BODY_CHARACTERS or len(plain) >= len(from_html)):
        return plain

    return from_html or plain


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
