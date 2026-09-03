"""Persian numerals, dates, and bidirectional text safety.

This module exists because "just send Persian text" is not enough. Telegram
renders messages with the Unicode Bidirectional Algorithm, and the UBA does
not know your intent -- it only knows character classes. Two failures happen
constantly in Persian bots and both look like the bot is broken:

1. **Trailing punctuation jumps.** In an RTL paragraph, `:` and `!` are
   neutral characters. Put one after a Latin word or a digit at the end of a
   line and the UBA resolves it to the *left* edge, so `Geek Turbo:` renders
   as `:Geek Turbo`. The fix is an RLM after the neutral run.

2. **Number ranges reverse.** `2 - 10` inside RTL text renders as `10 - 2`
   because the hyphen is neutral and gets absorbed into the RTL run. A range
   is a lie if it renders backwards, so ranges are wrapped in an isolate.

We use isolates (LRI/RLI/FSI + PDI) rather than the older embedding marks.
Isolates are the modern, correct tool: they stop the enclosed run from
influencing the direction of neighbouring text, which is exactly what we want
when dropping a Latin config name or an English server tag into a Persian
sentence.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

# -- Bidi control characters -------------------------------------------------

RLM = "\u200f"  # RIGHT-TO-LEFT MARK
LRM = "\u200e"  # LEFT-TO-RIGHT MARK
LRI = "\u2066"  # LEFT-TO-RIGHT ISOLATE
RLI = "\u2067"  # RIGHT-TO-LEFT ISOLATE
FSI = "\u2068"  # FIRST STRONG ISOLATE
PDI = "\u2069"  # POP DIRECTIONAL ISOLATE
ZWNJ = "\u200c"  # ZERO WIDTH NON-JOINER (Persian half-space)

PERSIAN_DIGITS = "\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9"
ASCII_DIGITS = "0123456789"
ARABIC_INDIC_DIGITS = "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"

_TO_PERSIAN = str.maketrans(ASCII_DIGITS + ARABIC_INDIC_DIGITS, PERSIAN_DIGITS * 2)
_TO_ASCII = str.maketrans(PERSIAN_DIGITS + ARABIC_INDIC_DIGITS, ASCII_DIGITS * 2)

# Arabic letters that leak in from copy-paste and phone keyboards. Persian
# users type these constantly; normalising them means a search for "کرج" also
# matches "كرج".
_ARABIC_TO_PERSIAN_LETTERS = str.maketrans(
    {
        "\u064a": "\u06cc",  # ARABIC YEH -> FARSI YEH
        "\u0649": "\u06cc",  # ALEF MAKSURA -> FARSI YEH
        "\u0643": "\u06a9",  # ARABIC KAF -> KEHEH
        "\u06c0": "\u0647",
        "\u0629": "\u0647",  # TEH MARBUTA -> HEH
    }
)

# Harakat / tatweel add nothing to a UI string and break equality checks.
_STRIP_DIACRITICS = re.compile(r"[\u064b-\u0652\u0640\u0670]")


def fa_digits(value: object) -> str:
    """Render any value with Persian-Indic numerals."""
    return str(value).translate(_TO_PERSIAN)


def en_digits(value: str) -> str:
    """Inverse of `fa_digits`. Used on every inbound user string.

    A user typing a coupon code or an amount on a Persian keyboard produces
    U+06F1 rather than `1`. `int()` actually accepts those, but string
    comparisons and regexes do not, so we normalise at the boundary.
    """
    return value.translate(_TO_ASCII)


def normalize_input(value: str) -> str:
    """Normalise a raw user-typed string: digits, letters, diacritics, spaces."""
    text = value.translate(_TO_ASCII).translate(_ARABIC_TO_PERSIAN_LETTERS)
    text = _STRIP_DIACRITICS.sub("", text)
    text = text.replace(ZWNJ, " ").replace("\u00a0", " ")
    for mark in (RLM, LRM, LRI, RLI, FSI, PDI):
        text = text.replace(mark, "")
    return " ".join(text.split())


def isolate(value: object) -> str:
    """Wrap a run so it cannot reorder its neighbours.

    Use for anything whose direction differs from the surrounding Persian:
    config names, UUIDs, server tags, usernames, URLs.
    """
    return f"{FSI}{value}{PDI}"


def ltr(value: object) -> str:
    """Force a run left-to-right regardless of its first strong character.

    `isolate` uses the *first strong* character to pick a direction, which is
    wrong for a string that starts with a digit or punctuation but is
    logically Latin -- `+98 912 ...` or `2/10`. This pins it.
    """
    return f"{LRI}{value}{PDI}"


def rtl_line(value: str) -> str:
    """Prefix a line with RLM so it establishes an RTL paragraph.

    Needed when a line *starts* with a neutral or Latin character -- an emoji,
    a bullet, or a digit -- but is logically Persian. Without this, a line
    beginning with an emoji is laid out left-to-right and the whole line
    renders mirrored.
    """
    return f"{RLM}{value}"


def fa_number(value: int | float, *, decimals: int = 0) -> str:
    """Group with thousands separators and render in Persian numerals."""
    if decimals:
        formatted = f"{value:,.{decimals}f}"
        # Persian uses ٫ as the decimal separator.
        formatted = formatted.replace(".", "\u066b")
    else:
        formatted = f"{round(value):,}"
    return fa_digits(formatted)


def toman(amount: int, *, unit: bool = True) -> str:
    """Format a Money amount (stored in Toman) for display.

    Wrapped in an isolate: the amount is a digit run followed by a Persian
    word, and without the isolate a trailing `:` or `!` in the caller's
    sentence detaches and flies to the wrong edge.
    """
    body = fa_number(amount)
    return isolate(f"{body} \u062a\u0648\u0645\u0627\u0646") if unit else isolate(body)


def percent(value: float) -> str:
    text = fa_number(value, decimals=0 if float(value).is_integer() else 1)
    return isolate(f"\u066a{text}")


def gib(value: float | None, *, compact: bool = False) -> str:
    """Render a traffic quota. `None` means unlimited -- never ۰.

    `compact` shortens the unit word for inline-keyboard labels, which Telegram
    truncates to one line: four characters saved there is the difference
    between showing the price and showing "\u06f2\u06f0\u06f0,...".
    """
    if value is None:
        return "\u0646\u0627\u0645\u062d\u062f\u0648\u062f"
    if value >= 1024:
        return isolate(
            f"{fa_number(value / 1024, decimals=1)} \u062a\u0631\u0627\u0628\u0627\u06cc\u062a"
        )
    if value < 1:
        return isolate(f"{fa_number(value * 1024)} \u0645\u06af\u0627\u0628\u0627\u06cc\u062a")
    formatted = fa_number(value, decimals=0 if float(value).is_integer() else 1)
    unit = "\u06af\u06cc\u06af" if compact else "\u06af\u06cc\u06af\u0627\u0628\u0627\u06cc\u062a"
    return isolate(f"{formatted} {unit}")


def ratio(used: float, total: float | None) -> str:
    """Render `used / total`. The slash is neutral, so the run is pinned LTR."""
    if total is None:
        return f"{gib(used)} \u0627\u0632 \u0646\u0627\u0645\u062d\u062f\u0648\u062f"
    return f"{gib(used)} \u0627\u0632 {gib(total)}"


# -- Jalali calendar ---------------------------------------------------------
#
# Implemented inline rather than pulling in `jdatetime`. The conversion is a
# well-defined arithmetic algorithm, it is thirty lines, and it removes a
# dependency from the critical path of every single message the bot sends.

_JALALI_MONTHS = (
    "\u0641\u0631\u0648\u0631\u062f\u06cc\u0646",
    "\u0627\u0631\u062f\u06cc\u0628\u0647\u0634\u062a",
    "\u062e\u0631\u062f\u0627\u062f",
    "\u062a\u06cc\u0631",
    "\u0645\u0631\u062f\u0627\u062f",
    "\u0634\u0647\u0631\u06cc\u0648\u0631",
    "\u0645\u0647\u0631",
    "\u0622\u0628\u0627\u0646",
    "\u0622\u0630\u0631",
    "\u062f\u06cc",
    "\u0628\u0647\u0645\u0646",
    "\u0627\u0633\u0641\u0646\u062f",
)
_WEEKDAYS = (
    "\u062f\u0648\u0634\u0646\u0628\u0647",
    "\u0633\u0647\u200c\u0634\u0646\u0628\u0647",
    "\u0686\u0647\u0627\u0631\u0634\u0646\u0628\u0647",
    "\u067e\u0646\u062c\u200c\u0634\u0646\u0628\u0647",
    "\u062c\u0645\u0639\u0647",
    "\u0634\u0646\u0628\u0647",
    "\u06cc\u06a9\u200c\u0634\u0646\u0628\u0647",
)


def to_jalali(value: date) -> tuple[int, int, int]:
    """Gregorian -> Jalali (year, month, day)."""
    gy, gm, gd = value.year, value.month, value.day
    g_d_m = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    gy2 = gy - 1600
    gm2 = gm - 1
    gd2 = gd - 1
    g_day_no = 365 * gy2 + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
    g_day_no += g_d_m[gm2] + gd2
    if gm > 2 and ((gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0):
        g_day_no += 1
    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053
    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365
    for i in range(11):
        month_len = 31 if i < 6 else 30
        if j_day_no < month_len:
            return jy, i + 1, j_day_no + 1
        j_day_no -= month_len
    return jy, 12, j_day_no + 1


def fa_date(value: datetime | date) -> str:
    """`۱۲ مرداد ۱۴۰۴`"""
    base = value.date() if isinstance(value, datetime) else value
    jy, jm, jd = to_jalali(base)
    return isolate(f"{fa_digits(jd)} {_JALALI_MONTHS[jm - 1]} {fa_digits(jy)}")


def fa_datetime(value: datetime) -> str:
    """`۱۲ مرداد ۱۴۰۴ ساعت ۱۴:۳۰`"""
    clock = ltr(f"{value.hour:02d}:{value.minute:02d}")
    return f"{fa_date(value)} \u0633\u0627\u0639\u062a {clock}"


def fa_weekday(value: datetime | date) -> str:
    base = value.date() if isinstance(value, datetime) else value
    return _WEEKDAYS[base.weekday()]


def fa_duration(days: int) -> str:
    """Render a package duration the way a shop would say it.

    ۳۰ -> یک ماهه, ۹۰ -> سه ماهه, ۳۶۵ -> یک‌ساله. Falls back to days.
    """
    named = {
        1: "\u06cc\u06a9\u200c\u0631\u0648\u0632\u0647",
        7: "\u0647\u0641\u062a\u06af\u06cc",
        14: "\u062f\u0648\u0647\u0641\u062a\u0647\u200c\u0627\u06cc",
        30: "\u06cc\u06a9\u200c\u0645\u0627\u0647\u0647",
        60: "\u062f\u0648\u0645\u0627\u0647\u0647",
        90: "\u0633\u0647\u200c\u0645\u0627\u0647\u0647",
        180: "\u0634\u0634\u200c\u0645\u0627\u0647\u0647",
        270: "\u0646\u0647\u200c\u0645\u0627\u0647\u0647",
        365: "\u06cc\u06a9\u200c\u0633\u0627\u0644\u0647",
    }
    if days in named:
        return named[days]
    if days % 30 == 0:
        return f"{fa_digits(days // 30)} \u0645\u0627\u0647\u0647"
    return f"{fa_digits(days)} \u0631\u0648\u0632\u0647"


def fa_relative(delta: timedelta) -> str:
    """Human remaining time. Always rounds *down* -- never promise more."""
    total = int(delta.total_seconds())
    if total <= 0:
        return "\u0645\u0646\u0642\u0636\u06cc \u0634\u062f\u0647"
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days >= 1:
        if hours:
            return f"{fa_digits(days)} \u0631\u0648\u0632 \u0648 {fa_digits(hours)} \u0633\u0627\u0639\u062a"
        return f"{fa_digits(days)} \u0631\u0648\u0632"
    if hours >= 1:
        if minutes:
            return f"{fa_digits(hours)} \u0633\u0627\u0639\u062a \u0648 {fa_digits(minutes)} \u062f\u0642\u06cc\u0642\u0647"
        return f"{fa_digits(hours)} \u0633\u0627\u0639\u062a"
    if minutes >= 1:
        return f"{fa_digits(minutes)} \u062f\u0642\u06cc\u0642\u0647"
    return "\u06a9\u0645\u062a\u0631 \u0627\u0632 \u06cc\u06a9 \u062f\u0642\u06cc\u0642\u0647"


def countdown(seconds: float) -> str:
    """Flash-sale countdown, pinned LTR so `۰۲:۱۴:۳۰` never reverses."""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return ltr(fa_digits(f"{hours:02d}:{minutes:02d}:{secs:02d}"))


def progress_bar(fraction: float, *, width: int = 10) -> str:
    """A filled/empty block bar.

    Built LTR then pinned, because block characters are neutral and a bar
    inside RTL text otherwise fills from the wrong end -- which reads as the
    exact opposite of the truth.
    """
    clamped = min(1.0, max(0.0, fraction))
    filled = round(clamped * width)
    return ltr("\u2588" * filled + "\u2591" * (width - filled))


def pluralize_days(days: int) -> str:
    return f"{fa_digits(days)} \u0631\u0648\u0632"


def truncate(value: str, limit: int) -> str:
    """Ellipsise without splitting a surrogate pair or leaving a dangling ZWNJ."""
    if len(value) <= limit:
        return value
    cut = value[: limit - 1].rstrip(ZWNJ + " ")
    return f"{cut}\u2026"
