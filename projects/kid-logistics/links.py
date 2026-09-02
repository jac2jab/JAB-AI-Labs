"""Turning a person and a message into something a phone will actually open.

Small, fiddly, and wrong by default — so it lives in one module with its own
tests rather than being scattered through templates.

**iOS and Android disagree about the SMS body.** Android follows RFC 5724 and
wants `sms:+15551234567?body=...`. iOS wants an ampersand instead:
`sms:+15551234567&body=...`, and given a question mark will open Messages with
an empty message. Apple's own documentation says the URL must not include
message text at all, which is not what the platform actually does. There is no
single string that works on both, so the app remembers which phone each parent
carries (auth.set_platform) rather than guessing per request.

**One recipient per link.** Multi-recipient `sms:` behaves inconsistently
across platforms and versions. It is also the wrong design: a button per person
is what gives the change screen its tick-off list, and the whole promise of
that screen is that nobody gets forgotten.

**Maps links are plain HTTPS**, which works everywhere, rather than the `geo:`
or `maps:` schemes which do not.

    python links.py
"""

from __future__ import annotations

import re
from urllib.parse import quote

IOS = "ios"
ANDROID = "android"

#: Phone numbers are normalised on the assumption that a bare 10-digit number
#: is North American. Stated rather than hidden: if this app ever leaves +1,
#: this is the function to revisit, and it is the only one.
DEFAULT_COUNTRY_CODE = "1"


def normalise_phone(raw: str | None) -> str | None:
    """`(555) 222-3333` -> `+15552223333`. None if there is nothing dialable.

    Anything already in +E.164 is left alone. Extensions and letters are
    dropped rather than guessed at.
    """
    if not raw:
        return None
    text = raw.strip()
    keep_plus = text.startswith("+")
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    if keep_plus:
        return "+" + digits
    if len(digits) == 10:
        return "+" + DEFAULT_COUNTRY_CODE + digits
    if len(digits) == 11 and digits.startswith(DEFAULT_COUNTRY_CODE):
        return "+" + digits
    # Something unusual — a short code, an international number typed without
    # a plus. Return the digits rather than mangling them into a wrong country.
    return "+" + digits


def sms_url(phone: str | None, body: str = "", platform: str = ANDROID) -> str | None:
    """A tap-to-text link with the message prefilled, for one recipient.

    Returns None when there is no number, so a template renders "no number on
    file" rather than a button that silently does nothing.
    """
    number = normalise_phone(phone)
    if not number:
        return None
    if not body:
        return f"sms:{number}"
    # safe="" so that &, ?, #, newlines and spaces are all percent-encoded and
    # cannot terminate the body early. A stray & in "pickup & dropoff" would
    # otherwise truncate the message on Android.
    encoded = quote(body, safe="")
    separator = "&" if platform == IOS else "?"
    return f"sms:{number}{separator}body={encoded}"


def tel_url(phone: str | None) -> str | None:
    """Tap to call. Identical on both platforms."""
    number = normalise_phone(phone)
    return f"tel:{number}" if number else None


def maps_url(address: str | None, platform: str = ANDROID) -> str | None:
    """Open a location. HTTPS, so it works with or without an app installed."""
    if not address or not address.strip():
        return None
    query = quote(address.strip(), safe="")
    host = "maps.apple.com" if platform == IOS else "maps.google.com"
    return f"https://{host}/?q={query}"


def maps_urls(address: str | None) -> dict[str, str]:
    """Both map links, for the settings screen and for anyone whose phone lies."""
    if not address or not address.strip():
        return {}
    return {"apple": maps_url(address, IOS), "google": maps_url(address, ANDROID)}


#: Schemes a check-in link may use. http/https cover Life360 and Find My web
#: links; a custom scheme covers an app deep link someone has found that works.
_SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.IGNORECASE)


def checkin_url(raw: str | None) -> str | None:
    """A 'did they get there' link, exactly as the user pasted it.

    Best-effort by design. Neither Find My nor Life360 publishes a documented
    URL scheme, and Find My has no public API at all, so this app does not
    pretend to integrate with either — it stores a link you found and gives you
    a button for it. A bare hostname is upgraded to https; anything without a
    plausible scheme is refused rather than rendered as a dead button.
    """
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    if _SCHEME.match(text):
        return text
    if "." in text and " " not in text:
        return "https://" + text
    return None


def _self_test() -> int:
    failures = 0

    def check(label, got, expected) -> None:
        nonlocal failures
        ok = got == expected
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {label:<52} {got!r}")

    # Numbers.
    check("formatted US number", normalise_phone("(555) 222-3333"), "+15552223333")
    check("dotted number", normalise_phone("555.222.3333"), "+15552223333")
    check("already E.164 left alone", normalise_phone("+15552223333"), "+15552223333")
    check("leading 1 handled", normalise_phone("1-555-222-3333"), "+15552223333")
    check("international plus kept", normalise_phone("+44 20 7946 0958"),
          "+442079460958")
    check("empty is None", normalise_phone(""), None)
    check("None is None", normalise_phone(None), None)
    check("letters alone are None", normalise_phone("call me"), None)

    body = "Hi — Ava is home sick, so I'm not able to drive to Soccer practice."

    # The platform split, asserted exactly.
    ios = sms_url("555-222-3333", body, IOS)
    android = sms_url("555-222-3333", body, ANDROID)
    check("iOS uses an ampersand", ios.startswith("sms:+15552223333&body="), True)
    check("Android uses a question mark",
          android.startswith("sms:+15552223333?body="), True)
    check("they differ by exactly one character",
          sum(a != b for a, b in zip(ios, android)), 1)
    check("no raw spaces survive", " " in ios, False)
    check("the apostrophe is encoded", "%27" in ios, True)
    check("the em dash is encoded", "%E2%80%94" in ios, True)

    # An ampersand in the message must not truncate it.
    amp = sms_url("5552223333", "pickup & dropoff swapped", ANDROID)
    check("ampersand in body is encoded", amp.count("&"), 0)
    check("and the whole body is there", "%26" in amp, True)

    # Newlines survive.
    multi = sms_url("5552223333", "Line one\nLine two", ANDROID)
    check("newline encoded", "%0A" in multi, True)

    check("no body, no separator", sms_url("5552223333"), "sms:+15552223333")
    check("no number, no link", sms_url(None, body), None)
    check("blank number, no link", sms_url("", body), None)

    # Calling.
    check("tel link", tel_url("(555) 222-3333"), "tel:+15552223333")
    check("no number, no tel", tel_url(None), None)

    # Maps.
    check("apple maps", maps_url("100 Riverside Dr, Anytown", IOS),
          "https://maps.apple.com/?q=100%20Riverside%20Dr%2C%20Anytown")
    check("google maps", maps_url("100 Riverside Dr, Anytown", ANDROID),
          "https://maps.google.com/?q=100%20Riverside%20Dr%2C%20Anytown")
    check("both offered", sorted(maps_urls("1 Main St")), ["apple", "google"])
    check("no address, no map", maps_url("   "), None)
    check("no address, no pair", maps_urls(None), {})

    # Check-in links, best effort and honest about it.
    check("https link kept", checkin_url("https://life360.com/x"),
          "https://life360.com/x")
    check("custom scheme kept", checkin_url("life360://circles"),
          "life360://circles")
    check("bare host upgraded", checkin_url("life360.com"), "https://life360.com")
    check("prose refused", checkin_url("ask Sarah where they are"), None)
    check("empty refused", checkin_url("  "), None)

    print()
    print(f"FAILURES: {failures}" if failures else "the links behave")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
