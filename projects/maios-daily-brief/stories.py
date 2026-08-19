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

# A block that is mostly bullet points is a feature list, a table of contents,
# or a link roundup rather than a story. Measured across the 36 stories from
# six real newsletters: every such block carried 5 or more list items, and the
# most any real story carried was 3.
LIST_ITEM_RE = re.compile(r"(?m)^\s*(?:\d+\.|\*|-)\s+\S")
MAX_LIST_ITEMS = 5

# How far back to look for an advertising label. "FROM OUR PARTNERS" sits on
# its own line immediately above the heading it labels, so an advert's own body
# never contains it — which is how a ZeroDrift pitch and a Mintlify pitch both
# scored 5/5 as new capabilities. The marker is a boundary signal, and reading
# it as a content signal was the bug.
SPONSOR_LOOKBACK_CHARACTERS = 200

# Only these announce the block beneath them. The wider SPONSOR_MARKERS list
# also holds "advertise in", which is a solicitation in the newsletter's own
# footer rather than a label — "Advertise in The Neuron here!" sits directly
# above the Grok 4.6 headline, and treating it as a label dropped the single
# most valuable story in the sample.
SPONSOR_LABEL_MARKERS = (
    "from our partner",
    "sponsored by",
    "presented by",
)


# Content that follows a story but is not part of it: the newsletter's own
# advertising, its quick-link roundup, and its footer. Without this the last
# story in an email absorbs everything after it, which reintroduced the exact
# bug splitting exists to remove — the Flock story scored on `anthropic` from
# an unrelated quick-link about Decart sitting in its tail.
TAIL_MARKERS = (
    "from our partner",
    "other news & articles",
    "other news and articles",
    "advertise in",
    "was this email forwarded",
    "unsubscribe",
)


def _trim_tail(body: str) -> str:
    """Cut a story body where the newsletter's furniture begins."""
    lowered = body.lower()
    cuts = [position for position in (lowered.find(m) for m in TAIL_MARKERS) if position > 0]

    return body[: min(cuts)].strip() if cuts else body


def _clean_title(title: str) -> str:
    """Strip markdown emphasis and surrounding punctuation from a headline."""
    title = re.sub(r"[*_`]+", "", title).strip()
    return title.strip(" .:-—")


def _is_sponsor(title: str, body: str) -> bool:
    """True when the newsletter labelled this block as advertising."""
    head = f"{title} {body[:300]}".lower()
    return any(marker in head for marker in SPONSOR_MARKERS)


def _preceded_by_sponsor(text: str, start: int) -> bool:
    """True when an advertising label sits just above this block's heading."""
    window = text[max(0, start - SPONSOR_LOOKBACK_CHARACTERS):start].lower()
    return any(marker in window for marker in SPONSOR_LABEL_MARKERS)


def _is_list_block(body: str) -> bool:
    """True when a block is a bullet list rather than a story."""
    return len(LIST_ITEM_RE.findall(body)) >= MAX_LIST_ITEMS


def _is_house_promotion(title: str, sender: str) -> bool:
    """True when a newsletter is advertising itself.

    "New from The Neuron: AI Explained" scored 5/5 twice. A recurring house
    section names its own publication, and a real story about someone else
    does not, so the sender's name in the headline is the signal — no list of
    section names to keep up to date.
    """
    sender = sender.strip().lower()
    return bool(sender) and sender in title.lower()


def _split_on(pattern: re.Pattern, text: str) -> list[dict]:
    """Cut text into blocks starting at each match of a headline pattern."""
    matches = list(pattern.finditer(text))
    blocks = []

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append(
            {
                "title": _clean_title(match.group(1)),
                "body": _trim_tail(text[match.end():end].strip()),
                "start": match.start(),
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
            {
                "title": _clean_title(title),
                "body": _trim_tail(text[body_start:end].strip()),
                "start": start,
            }
        )

    return blocks


def _keep(blocks: list[dict], text: str, sender: str) -> list[dict]:
    """Drop everything that is not a story.

    Advertising is recognized by the label above the heading, not inside the
    block. Bullet lists and house promotion are recognized structurally. All
    of it happens before the model is ever asked anything.
    """
    return [
        block
        for block in blocks
        if len(block["body"]) >= MIN_STORY_CHARACTERS
        and MIN_TITLE_CHARACTERS <= len(block["title"]) <= MAX_TITLE_CHARACTERS
        and not FRAGMENT_TITLE_RE.match(block["title"])
        and not _is_sponsor(block["title"], block["body"])
        and not _preceded_by_sponsor(text, block["start"])
        and not _is_list_block(block["body"])
        and not _is_house_promotion(block["title"], sender)
    ]


def split_stories(email: dict) -> list[dict]:
    """Split one email into its stories, or return it whole if it is not a roundup.

    Returns records carrying the parent email's identity, so a story can always
    be traced back to the mail it came from.
    """
    body = email.get("body", "")

    # The three senders here use three different markups, so both structures
    # are tried and whichever recovers more real stories wins.
    sender = email.get("sender", "")
    candidates = [
        _keep(_split_on(HEADING_RE, body), body, sender),
        _keep(_split_on_link_marker(body), body, sender),
    ]
    kept = max(candidates, key=len)

    if len(kept) < 2:
        # Not a roundup, or a structure this does not understand. Treat the
        # email as a single story rather than dropping it.
        return [
            {
                "subject": email.get("subject", ""),
                "body": body[:MAX_STORY_CHARACTERS],
                "sender": email.get("sender", ""),
                "parent_subject": email.get("subject", ""),
                "split": False,
            }
        ]

    return [
        {
            "subject": block["title"],
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
