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
# Deliberately not #{4,6}: Superhuman labels its sections "##### **TODAY IN
# AI**", which are banners rather than stories.
HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,3}[ \t]+(\S.*?)[ \t]*$", re.MULTILINE)

# Superhuman numbers its lead stories in bold and runs the body straight on
# from the colon:
#
#     **1. Stripe becomes one of the first non-AI companies ...: **In an
#     official letter to investors ...
#
# These sit above the first markdown heading, so an email split on headings
# alone loses all of them - including the story the email is named after.
#
# The trailing lookahead is what separates a story headline from a tutorial
# step. Futurepedia numbers the steps of one article the same way -
# "**1. Turn on memory first**" - but the bold span ends the line, while
# Superhuman's headline runs straight into its story on the same line. Without
# it, one Futurepedia article fragmented into nine "stories".
NUMBERED_ITEM_RE = re.compile(
    r"^\*\*\d+\.[ \t]*([^*]{10,120}?)[ \t]*:?[ \t]*\*\*(?=[ \t]*\S)", re.MULTILINE
)

# Techpresso trails each story headline with the link text "LINK", but the
# headline sits mid-line: the previous story's last sentence runs straight into
# it, so anchoring to the line start swallows that sentence. The emoji that
# prefixes every headline is the real boundary. Requiring one also separates
# the six full stories from the dozen emoji-less quick links that share the
# same "LINK" marker.
LINK_MARKER_RE = re.compile(r"\s+LINK\b")
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u26FF\u2700-\u27BF]")

# TLDR, TLDR AI, and TLDR Data ship hard-wrapped plain text and mark every
# headline with its kind and a footnote number:
#
#     EARLY OUTPUTS OF MUSE VIDEO MODEL FROM META (3 MINUTE READ) [7]
#     ROUTER (WEBSITE) [8]
#     MUCH REAL WORK IT DOES (SPONSOR) [4]
#
# The headline is upper case and wraps across lines, so the marker is found
# first and the title read backwards from it — the same approach Techpresso
# needed. (SPONSOR) labels the advert in the same breath, which is the
# cleanest sponsor signal any of these senders provides.
# The hard wrap can fall inside the marker itself - "(3 MINUTE\nREAD) [10]" -
# so the kind has to be allowed to span lines. Without this the headline is not
# seen at all and the story above it absorbs the whole next story: the mRNA
# cancer vaccine item swallowed Unitree's humanoid robots.
TLDR_MARKER_RE = re.compile(r"\(([A-Z0-9][A-Z0-9\s]{1,28})\)\s*\[\d+\]")
TLDR_SPONSOR_KIND = "SPONSOR"

# TLDR-family newsletters banner each section on its own upper-case line -
# "DEEP DIVES", "LAUNCHES & TOOLS", "QUICK LINKS". The banner says what kind of
# item follows far more reliably than a model reading the item does, so it is
# captured here and used as a ceiling on the score rather than asked about.
SECTION_BANNER_RE = re.compile(
    r"(?m)^[ \t]*([A-Z][A-Z0-9 ,&'\-/]{5,58})[ \t]*$"
)

# How far back to look for the banner a story sits under.
SECTION_LOOKBACK_CHARACTERS = 4000

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
    """Strip markdown emphasis, footnote references, and edge punctuation."""
    title = re.sub(r"[*_`]+", "", title).strip()
    # TLDR ends the previous story with a footnote reference like "[20]!" that
    # the backward walk picks up ahead of the real headline.
    title = re.sub(r"^\s*\[\d+\][!?.]?\s*", "", title)
    return title.strip(" .:-—")


def _is_sponsor(title: str, body: str) -> bool:
    """True when the newsletter labelled this block as advertising."""
    head = f"{title} {body[:300]}".lower()
    return any(marker in head for marker in SPONSOR_MARKERS)


def _preceded_by_sponsor(text: str, start: int) -> bool:
    """True when an advertising label sits just above this block's heading."""
    window = text[max(0, start - SPONSOR_LOOKBACK_CHARACTERS):start].lower()
    return any(marker in window for marker in SPONSOR_LABEL_MARKERS)


def _section_above(text: str, start: int) -> str:
    """The section banner a story sits under, or empty when there is none.

    Advertising labels are upper case on their own line and look exactly like a
    banner, so they have to be skipped: without this, 23 of 149 stories came
    back filed under "FROM OUR PARTNER", including two genuine security stories.
    """
    window_start = max(0, start - SECTION_LOOKBACK_CHARACTERS)

    for banner in reversed(list(SECTION_BANNER_RE.finditer(text, window_start, start))):
        name = " ".join(banner.group(1).split())

        if any(marker in name.lower() for marker in SPONSOR_MARKERS):
            continue

        return name

    return ""


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


def _heads_from_pattern(pattern: re.Pattern, text: str) -> list[dict]:
    """Headline positions from a regex whose first group is the title."""
    return [
        {
            "start": match.start(),
            "body_start": match.end(),
            "title": _clean_title(match.group(1)),
            "sponsored": False,
        }
        for match in pattern.finditer(text)
    ]


def _heads_from_link_marker(text: str) -> list[dict]:
    """Techpresso headlines: an emoji-led title immediately before "LINK"."""
    heads = []

    for match in LINK_MARKER_RE.finditer(text):
        window_start = max(0, match.start() - MAX_TITLE_CHARACTERS)
        emojis = list(EMOJI_RE.finditer(text[window_start:match.start()]))

        if not emojis:
            continue

        start = window_start + emojis[-1].start()
        heads.append(
            {
                "start": start,
                "body_start": match.end(),
                "title": _clean_title(text[start:match.start()]),
                "sponsored": False,
            }
        )

    return heads


def _heads_from_caps_marker(text: str) -> list[dict]:
    """TLDR headlines: an upper-case title immediately before its kind marker."""
    heads = []

    for match in TLDR_MARKER_RE.finditer(text):
        limit = max(0, match.start() - MAX_TITLE_CHARACTERS)
        start = match.start()

        # Walk back over the upper-case headline, stopping at the first
        # lower-case letter, which belongs to the previous story's prose, and
        # at a blank line. TLDR puts its section banners ("HEADLINES &
        # LAUNCHES") in upper case too, a paragraph above the headline, so
        # without the blank-line stop the banner is swallowed into the title.
        while start > limit and not text[start - 1].islower():
            if text[start - 1] == "\n" and text[limit:start - 1].rstrip(" \t").endswith("\n"):
                break

            start -= 1

        heads.append(
            {
                "start": start,
                "body_start": match.end(),
                "title": _clean_title(" ".join(text[start:match.start()].split())),
                # A (SPONSOR) block is still a boundary — the story above it
                # ends here — but is never kept as a story itself. The kind is
                # whitespace-normalized because the wrap can land inside it.
                "sponsored": " ".join(match.group(1).split()) == TLDR_SPONSOR_KIND,
            }
        )

    return heads


def _blocks_from_heads(heads: list[dict], text: str) -> list[dict]:
    """Cut the text at every headline found, whichever pattern found it.

    One newsletter can use more than one structure at once. Superhuman numbers
    its three lead stories in bold and gives its feature stories markdown
    headings, so choosing a single winning pattern per email lost whichever set
    came second — here the three most newsworthy items, including the story the
    email is named after. Merging the boundaries keeps both.
    """
    ordered = sorted(heads, key=lambda head: head["start"])
    merged: list[dict] = []

    for head in ordered:
        # Two patterns finding the same headline produce two heads a few
        # characters apart; keep the first and drop the echo.
        if merged and head["start"] - merged[-1]["start"] < MIN_TITLE_CHARACTERS:
            continue

        merged.append(head)

    blocks = []

    for index, head in enumerate(merged):
        if head["sponsored"]:
            continue

        end = merged[index + 1]["start"] if index + 1 < len(merged) else len(text)
        blocks.append(
            {
                "title": head["title"],
                "body": _trim_tail(text[head["body_start"]:end].strip()),
                "start": head["start"],
                "section": _section_above(text, head["start"]),
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

    # Every structure is tried and the boundaries are pooled, because a single
    # newsletter can use two at once.
    heads = (
        _heads_from_pattern(HEADING_RE, body)
        + _heads_from_pattern(NUMBERED_ITEM_RE, body)
        + _heads_from_link_marker(body)
        + _heads_from_caps_marker(body)
    )
    kept = _keep(_blocks_from_heads(heads, body), body, sender)

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
            "section": block.get("section", ""),
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
