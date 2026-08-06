"""Jalali calendar support for chart axes.

Analytics buckets are computed in Gregorian because that is what timestamps
are, but every label an Iranian operator reads must be Jalali. Doing the
conversion here keeps it out of the presentation layer, where the bot, the
Mini App and the admin panel would each grow their own copy.

The algorithm is the standard 33-year-cycle conversion. It is exact for the
range this product will ever see.
"""

from __future__ import annotations

from datetime import date

MONTH_NAMES_FA: tuple[str, ...] = (
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

WEEKDAY_NAMES_FA: tuple[str, ...] = (
    "\u062f\u0648\u0634\u0646\u0628\u0647",
    "\u0633\u0647\u200c\u0634\u0646\u0628\u0647",
    "\u0686\u0647\u0627\u0631\u0634\u0646\u0628\u0647",
    "\u067e\u0646\u062c\u0634\u0646\u0628\u0647",
    "\u062c\u0645\u0639\u0647",
    "\u0634\u0646\u0628\u0647",
    "\u06cc\u06a9\u0634\u0646\u0628\u0647",
)

PERSIAN_DIGITS = "\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9"
_TO_PERSIAN = str.maketrans("0123456789", PERSIAN_DIGITS)

_GREGORIAN_MONTH_OFFSETS = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)


def fa_digits(value: object) -> str:
    return str(value).translate(_TO_PERSIAN)


def _is_gregorian_leap(year: int) -> bool:
    return (year % 4 == 0 and year % 100 != 0) or year % 400 == 0


def to_jalali(value: date) -> tuple[int, int, int]:
    """Convert a Gregorian date to a ``(year, month, day)`` Jalali triple."""
    gy, gm, gd = value.year, value.month, value.day

    gy2, gm2, gd2 = gy - 1600, gm - 1, gd - 1
    day_no = (
        365 * gy2
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        + _GREGORIAN_MONTH_OFFSETS[gm2]
        + gd2
    )
    if gm > 2 and _is_gregorian_leap(gy):
        day_no += 1

    day_no -= 79
    cycles, day_no = divmod(day_no, 12053)
    jy = 979 + 33 * cycles + 4 * (day_no // 1461)
    day_no %= 1461

    if day_no >= 366:
        jy += (day_no - 1) // 365
        day_no = (day_no - 1) % 365

    if day_no < 186:
        jm, jd = 1 + day_no // 31, 1 + day_no % 31
    else:
        remainder = day_no - 186
        jm, jd = 7 + remainder // 30, 1 + remainder % 30

    return jy, jm, jd


def jalali_date_fa(value: date) -> str:
    """``\u06f1\u06f4\u06f0\u06f5/\u06f0\u06f5/\u06f1\u06f2`` -- compact, for dense table cells."""
    jy, jm, jd = to_jalali(value)
    return fa_digits(f"{jy}/{jm:02d}/{jd:02d}")


def jalali_day_label(value: date) -> str:
    """``\u06f1\u06f2 \u0645\u0631\u062f\u0627\u062f`` -- for a daily chart axis, where the year is noise."""
    _, jm, jd = to_jalali(value)
    return f"{fa_digits(jd)} {MONTH_NAMES_FA[jm - 1]}"


def jalali_month_label(value: date, *, with_year: bool = True) -> str:
    """``\u0645\u0631\u062f\u0627\u062f \u06f1\u06f4\u06f0\u06f5`` -- for a monthly chart axis."""
    jy, jm, _ = to_jalali(value)
    name = MONTH_NAMES_FA[jm - 1]
    return f"{name} {fa_digits(jy)}" if with_year else name


def jalali_weekday(value: date) -> str:
    return WEEKDAY_NAMES_FA[value.weekday()]


__all__ = [
    "MONTH_NAMES_FA",
    "WEEKDAY_NAMES_FA",
    "fa_digits",
    "jalali_date_fa",
    "jalali_day_label",
    "jalali_month_label",
    "jalali_weekday",
    "to_jalali",
]
