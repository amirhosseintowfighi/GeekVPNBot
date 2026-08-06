"""FAQ content invariants.

The FAQ is data rather than handler code so it can move behind the admin
panel later. These tests protect the structural promises the handlers rely
on, plus the one policy statement the business cares most about.
"""

from __future__ import annotations

from geekvpn.presentation.bot import faq_content as F


class TestStructure:
    def test_sections_exist(self) -> None:
        assert len(F.FAQ) >= 3

    def test_section_keys_unique(self) -> None:
        keys = [s.key for s in F.FAQ]
        assert len(keys) == len(set(keys))

    def test_entry_keys_globally_unique(self) -> None:
        """Entry keys travel inside callback data, so a collision would route
        the customer to the wrong answer."""
        keys = [e.key for s in F.FAQ for e in s.entries]
        assert len(keys) == len(set(keys))

    def test_every_section_has_entries(self) -> None:
        assert all(s.entries for s in F.FAQ)

    def test_lookup_tables_are_complete(self) -> None:
        assert set(F.SECTIONS_BY_KEY) == {s.key for s in F.FAQ}
        assert set(F.ENTRIES_BY_KEY) == {e.key for s in F.FAQ for e in s.entries}


class TestContent:
    def test_questions_and_answers_are_nonempty(self) -> None:
        for section in F.FAQ:
            for entry in section.entries:
                assert entry.question_fa.strip()
                assert entry.answer_fa.strip()

    def test_everything_is_persian(self) -> None:
        """No stray English leaked into customer-facing copy."""
        for section in F.FAQ:
            assert any("\u0600" <= ch <= "\u06ff" for ch in section.title_fa)
            for entry in section.entries:
                assert any("\u0600" <= ch <= "\u06ff" for ch in entry.answer_fa)

    # Brand names are spelled the way the user will search for them in their app
    # store; "v۲rayNG" would be correct Persian and useless.
    PRODUCT_NAMES = ("v2rayNG",)

    def test_no_latin_digits_in_answers(self) -> None:
        for entry in F.ENTRIES_BY_KEY.values():
            answer = entry.answer_fa
            for name in self.PRODUCT_NAMES:
                answer = answer.replace(name, "")
            assert not (set(answer) & set("0123456789"))


class TestPolicyIsStated:
    def test_quota_answer_exists(self) -> None:
        """The no-top-up rule is the single most common support question;
        it must be answerable without a human."""
        assert "quota" in F.ENTRIES_BY_KEY

    def test_payment_methods_are_documented(self) -> None:
        combined = " ".join(e.answer_fa for e in F.ENTRIES_BY_KEY.values())
        # Card-to-card and crypto are the two live methods today.
        assert "\u06a9\u0627\u0631\u062a" in combined
