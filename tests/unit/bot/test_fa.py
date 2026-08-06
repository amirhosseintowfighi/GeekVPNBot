"""Persian formatting and bidi handling.

These are the functions every screen passes through, so a regression here is
visible on literally every message the bot sends.
"""

from __future__ import annotations

from datetime import date, timedelta

from geekvpn.presentation.bot.ui import fa

PERSIAN = set(fa.PERSIAN_DIGITS)
LATIN = set("0123456789")


class TestDigits:
    def test_converts_every_latin_digit(self) -> None:
        assert fa.fa_digits("0123456789") == fa.PERSIAN_DIGITS

    def test_leaves_non_digits_alone(self) -> None:
        out = fa.fa_digits("a1b2")
        assert out[0] == "a" and out[2] == "b"
        assert not (set(out) & LATIN)

    def test_accepts_non_string_input(self) -> None:
        assert not (set(fa.fa_digits(1234)) & LATIN)

    def test_en_digits_round_trips(self) -> None:
        assert fa.en_digits(fa.fa_digits("90210")) == "90210"


class TestNormalizeInput:
    """Whatever the user's keyboard produced must become parseable."""

    def test_persian_digits_become_latin(self) -> None:
        assert "500000" in fa.normalize_input(fa.fa_digits("500000"))

    def test_is_idempotent(self) -> None:
        once = fa.normalize_input("\u06f1\u06f2\u06f3")
        assert fa.normalize_input(once) == once


class TestBidi:
    def test_isolate_wraps_in_a_matched_pair(self) -> None:
        out = fa.isolate("123")
        assert out.endswith(fa.PDI)
        assert out[0] in (fa.FSI, fa.LRI, fa.RLI)

    def test_ltr_wraps_and_closes(self) -> None:
        out = fa.ltr("@geekvpn")
        assert out.endswith(fa.PDI)
        assert "@geekvpn" in out

    def test_isolation_is_balanced(self) -> None:
        """An unmatched isolate leaks into the rest of the message."""
        out = fa.isolate("1.2.3.4")
        opens = sum(out.count(c) for c in (fa.LRI, fa.RLI, fa.FSI))
        assert opens == out.count(fa.PDI)


class TestMoneyAndNumbers:
    def test_toman_uses_persian_digits(self) -> None:
        assert not (set(fa.toman(250_000)) & LATIN)

    def test_toman_groups_thousands(self) -> None:
        # Some separator must appear; a bare 7-digit run is unreadable.
        assert any(ch not in PERSIAN for ch in fa.toman(1_000_000, unit=False))

    def test_toman_unit_flag_changes_output(self) -> None:
        assert fa.toman(1000, unit=True) != fa.toman(1000, unit=False)

    def test_fa_number_zero(self) -> None:
        assert fa.fa_number(0) == "\u06f0"

    def test_percent_is_persian(self) -> None:
        assert not (set(fa.percent(25)) & LATIN)


class TestGibAndRatio:
    def test_gib_none_is_not_a_crash(self) -> None:
        assert isinstance(fa.gib(None), str)
        assert fa.gib(None) != ""

    def test_gib_is_persian(self) -> None:
        assert not (set(fa.gib(12.5)) & LATIN)

    def test_ratio_handles_unlimited(self) -> None:
        assert isinstance(fa.ratio(3.0, None), str)


class TestJalali:
    def test_returns_a_triple(self) -> None:
        y, m, d = fa.to_jalali(date(2026, 8, 3))
        assert 1400 <= y <= 1420
        assert 1 <= m <= 12
        assert 1 <= d <= 31

    def test_nowruz_is_month_one_day_one(self) -> None:
        """21 March 2026 is 1 Farvardin 1405 - the calendar's anchor."""
        assert fa.to_jalali(date(2026, 3, 21)) == (1405, 1, 1)

    def test_day_before_nowruz_is_end_of_esfand(self) -> None:
        y, m, _ = fa.to_jalali(date(2026, 3, 20))
        assert (y, m) == (1404, 12)

    def test_fa_date_is_persian(self) -> None:
        assert not (set(fa.fa_date(date(2026, 8, 3))) & LATIN)

    def test_fa_weekday_is_nonempty(self) -> None:
        assert fa.fa_weekday(date(2026, 8, 3)).strip()


class TestDurationsAndCountdown:
    def test_fa_duration_is_persian(self) -> None:
        assert not (set(fa.fa_duration(30)) & LATIN)

    def test_fa_relative_past_and_future_differ(self) -> None:
        past = fa.fa_relative(timedelta(days=-2))
        future = fa.fa_relative(timedelta(days=2))
        assert past != future

    def test_countdown_never_negative_looking(self) -> None:
        assert "-" not in fa.countdown(-5)


class TestProgressBar:
    # progress_bar pins the bar LTR, so the string carries two bidi isolate
    # marks that are not part of the bar itself.
    @staticmethod
    def _blocks(bar: str) -> str:
        return bar.strip("⁦⁩")

    def test_width_is_respected(self) -> None:
        assert len(self._blocks(fa.progress_bar(0.5, width=10))) == 10

    def test_clamps_out_of_range(self) -> None:
        assert len(self._blocks(fa.progress_bar(5.0, width=8))) == 8
        assert len(self._blocks(fa.progress_bar(-1.0, width=8))) == 8

    def test_empty_and_full_differ(self) -> None:
        assert fa.progress_bar(0.0) != fa.progress_bar(1.0)


class TestTruncate:
    def test_short_text_untouched(self) -> None:
        assert fa.truncate("\u0633\u0644\u0627\u0645", 20) == "\u0633\u0644\u0627\u0645"

    def test_long_text_respects_limit(self) -> None:
        assert len(fa.truncate("\u0627" * 100, 20)) <= 20
