"""Output escaping for the two places user text is rendered.

The two surfaces
----------------
1. **Telegram messages.** The bot sends ``parse_mode=HTML`` (see
   ``TelegramSettings``). Any customer-supplied text placed in such a message is
   parsed as markup. A support subject containing ``<b>`` is a formatting bug; a
   subject containing an unclosed tag makes the Telegram API reject the whole
   message, so a customer can make our own notifications undeliverable. That is
   a real availability bug, not a theoretical XSS.
2. **The admin panel and Mini App.** Both are React, which escapes text nodes on
   its own, so this module is not what protects them - the Content Security
   Policy and React's own escaping are. What this module adds is protection for
   the places React's guarantee does **not** hold: URLs put into ``href``, which
   React will happily render as ``javascript:``.

What is deliberately absent
---------------------------
No HTML sanitiser that tries to permit "safe" tags. Allow-listing tags in
customer text means writing an HTML parser, and a partial HTML parser is a
vulnerability. Customer text is escaped, never sanitised.
"""

from __future__ import annotations

from typing import Final

#: The five characters Telegram's HTML parser treats as markup. The order
#: matters: ampersand must be replaced first, otherwise the ampersands
#: introduced by the later replacements are escaped again into ``&amp;lt;``.
_HTML_REPLACEMENTS: Final = (
    ("&", "&amp;"),
    ("<", "&lt;"),
    (">", "&gt;"),
    ('"', "&quot;"),
    ("'", "&#39;"),
)

#: Directional overrides. These do not break markup, they break *reading*: they
#: can visually reverse a rendered string, which is how "مبلغ 50,000" can be
#: made to look like a different number in a support ticket or an admin list.
#: Persian text legitimately needs ZWNJ (U+200C) and the RLM/LRM marks, so only
#: the override and isolate controls are stripped.
_BIDI_OVERRIDES: Final = (
    "\u202a",  # LEFT-TO-RIGHT EMBEDDING
    "\u202b",  # RIGHT-TO-LEFT EMBEDDING
    "\u202c",  # POP DIRECTIONAL FORMATTING
    "\u202d",  # LEFT-TO-RIGHT OVERRIDE
    "\u202e",  # RIGHT-TO-LEFT OVERRIDE
    "\u2066",  # LEFT-TO-RIGHT ISOLATE
    "\u2067",  # RIGHT-TO-LEFT ISOLATE
    "\u2068",  # FIRST STRONG ISOLATE
    "\u2069",  # POP DIRECTIONAL ISOLATE
)

#: Schemes that may appear in a link we render. Everything else is dropped.
SAFE_URL_SCHEMES: Final = frozenset({"http", "https", "tg", "mailto"})


def strip_controls(value: str) -> str:
    """Remove control characters that corrupt logs and rendered output.

    Newlines and tabs survive: they are legitimate in a ticket body. A NUL byte
    or an ANSI escape does not - the latter can rewrite an operator's terminal
    when logs are tailed, which is a genuine attack on the person reading them.
    """
    text = "".join(
        character
        for character in (value or "")
        if character in "\n\r\t" or (ord(character) >= 32 and ord(character) != 127)
    )
    for override in _BIDI_OVERRIDES:
        text = text.replace(override, "")
    return text


def escape_html(value: str) -> str:
    """Escape customer text for a Telegram ``parse_mode=HTML`` message."""
    text = strip_controls(value)
    for character, replacement in _HTML_REPLACEMENTS:
        text = text.replace(character, replacement)
    return text


def escape_html_attribute(value: str) -> str:
    """Escape for use inside a quoted attribute value.

    Newlines are dropped here, unlike in body text: a newline inside an attribute
    ends the attribute in several lenient parsers.
    """
    return escape_html(value).replace("\n", " ").replace("\r", " ")


def safe_url(value: str) -> str | None:
    """Return the URL if its scheme is allowed, otherwise ``None``.

    ``javascript:`` is the obvious case. The subtler ones this catches are
    ``data:text/html`` (a whole document in a link) and leading whitespace or
    control characters, which browsers strip before parsing the scheme - so
    ``\\x01javascript:alert(1)`` is a working payload against a naive
    ``startswith`` check.
    """
    text = (value or "").strip()
    text = "".join(character for character in text if ord(character) > 32)
    if not text:
        return None
    if text.startswith("//"):
        # Protocol-relative: inherits the page scheme. Harmless in a browser,
        # meaningless to Telegram, and ambiguous enough to refuse.
        return None
    if ":" not in text:
        # A relative path. Safe, and used by the panel for internal links.
        return text if not text.startswith("\\") else None
    scheme = text.split(":", 1)[0].lower()
    if scheme not in SAFE_URL_SCHEMES:
        return None
    return text


def truncate_for_display(value: str, limit: int = 200) -> str:
    """Shorten text for a notification or an admin list cell.

    Truncation happens **after** escaping in the caller's order of operations,
    which is why the ellipsis is added here rather than by slicing an escaped
    string elsewhere: cutting ``&amp;`` in half produces ``&am``, which is
    rendered literally, and cutting a Telegram tag in half breaks the message.
    """
    text = strip_controls(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "\u2026"


__all__ = [
    "SAFE_URL_SCHEMES",
    "escape_html",
    "escape_html_attribute",
    "safe_url",
    "strip_controls",
    "truncate_for_display",
]
