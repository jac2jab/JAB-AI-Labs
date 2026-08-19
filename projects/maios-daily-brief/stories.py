"""Split roundup newsletters into their individual stories.

A newsletter is not one item. Techpresso ships six stories under one subject
line, so scoring or summarizing the whole email lets story seven's vocabulary
speak for the subject — which is how an Apple/Siri headline scored 5/5 on
`openai` in v0.4.1.

Splitting is done here in code rather than by asking a model to "find the
stories", for the same reason section membership is enforced in the SE
generator: a rule the code applies holds, and a rule the prompt requests does
not. The model's job starts after the structure is known.
"""

from __future__ import annotations

import re

# Each story is capped on its own. The v0.4 pipeline capped the whole email at
# 4,000 characters, which discarded ~60% of every roundup — including, in the
# Apple/Siri case, the story named in the subject line.
MAX_STORY_CHARACTERS = 1500

# A title shorter than this is furniture ("Caption:"); longer than this is a
# paragraph that happened to match, not a headline.
MIN_TITLE_CHARACTERS = 12
MAX_TITLE_CHARACTERS = 120

# Story bodies below this are table-of-contents entries, not articles.
MIN_STORY_CHARACTERS = 200

# Markers a newsletter uses to label its own advertising. Only explicit ones
# are dropped here; an unlabelled ad is left for relevance scoring to reject,
# because guessing at it in code would also drop real stories.
SPONSOR_MARKERS = (
    "from our partner",
    "advertise in",
    "together with",
    "sponsored by",
    "presented by",
)

# Markdown-style headings: The Neuron uses "# ", Smarter with AI uses "## ".
HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,3}[ \t]+(\S.*?)[ \t]*$", re.MULTILINE)

# Techpresso trails each story headline with the link text "LINK", but the
# headline sits mid-line: the previous story's last sentence runs straight into
# it, so anchoring to the line start swallows that sentence. The emoji that
# prefixes every headline is the real boundary. Requiring one also separates
# the six full stories from the dozen emoji-less quick links that share the
# same "LINK" marker.
LINK_MARKER_RE = re.compile(r"\s+LINK\b")
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u26FF\u2700-\u27BF]")

# Numbered steps are parts of one tutorial, not separate stories. Tuned against
# the Smarter with AI sample; a wider sample will surface more of these.
FRAGMENT_TITLE_RE = re.compile(r"^step\s+\d", re.IGNORECASE)


def _clean_title(title: str) -> str:
    """Strip markdown emphasis and surrounding punctuation from a headline."""
    title = re.sub(r"[*_`]+", "", title).strip()
    return title.strip(" .:-—")


def _is_sponsor(title: str, body: str) -> bool:
    """True when the newsletter labelled this block as advertising."""
    head = f"{title} {body[:300]}".lower()
    return any(marker in head for marker in SPONSOR_MARKERS)


def _split_on(pattern: re.Pattern, text: str) -> list[dict]:
    """Cut text into blocks starting at each match of a headline pattern."""
    matches = list(pattern.finditer(text))
    blocks = []

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append(
            {
                "title": _clean_title(match.group(1)),
                "body": text[match.end():end].strip(),
            }
        )

    return blocks


def _split_on_link_marker(text: str) -> list[dict]:
    """Cut Techpresso-style text where an emoji-led headline precedes "LINK"."""
    heads = []

    for match in LINK_MARKER_RE.finditer(text):
        window_start = max(0, match.start() - MAX_TITLE_CHARACTERS)
        emojis = list(EMOJI_RE.finditer(text[window_start:match.start()]))

        if not emojis:
            continue

        start = window_start + emojis[-1].start()
        heads.append((start, match.end(), text[start:match.start()]))

    blocks = []

    for index, (start, body_start, title) in enumerate(heads):
        end = heads[index + 1][0] if index + 1 < len(heads) else len(text)
        blocks.append(
            {"title": _clean_title(title), "body": text[body_start:end].strip()}
        )

    return blocks


def _keep(blocks: list[dict]) -> list[dict]:
    """Drop table-of-contents stubs, labelled adverts, and tutorial fragments."""
    return [
        block
        for block in blocks
        if len(block["body"]) >= MIN_STORY_CHARACTERS
        and MIN_TITLE_CHARACTERS <= len(block["title"]) <= MAX_TITLE_CHARACTERS
        and not FRAGMENT_TITLE_RE.match(block["title"])
        and not _is_sponsor(block["title"], block["body"])
    ]


def split_stories(email: dict) -> list[dict]:
    """Split one email into its stories, or return it whole if it is not a roundup.

    Returns records carrying the parent email's identity, so a story can always
    be traced back to the mail it came from.
    """
    body = email.get("body", "")

    # The three senders here use three different markups, so both structures
    # are tried and whichever recovers more real stories wins.
    candidates = [
        _keep(_split_on(HEADING_RE, body)),
        _keep(_split_on_link_marker(body)),
    ]
    kept = max(candidates, key=len)

    if len(kept) < 2:
        # Not a roundup, or a structure this does not understand. Treat the
        # email as a single story rather than dropping it.
        return [
            {
                "title": email.get("subject", ""),
                "body": body[:MAX_STORY_CHARACTERS],
                "sender": email.get("sender", ""),
                "parent_subject": email.get("subject", ""),
                "split": False,
            }
        ]

    return [
        {
            "title": block["title"],
            "body": block["body"][:MAX_STORY_CHARACTERS],
            "sender": email.get("sender", ""),
            "parent_subject": email.get("subject", ""),
            "split": True,
        }
        for block in kept
    ]


def split_all(emails: list[dict]) -> list[dict]:
    """Split every email, flattening the result into one list of stories."""
    stories = []

    for email in emails:
        stories.extend(split_stories(email))

    return stories
