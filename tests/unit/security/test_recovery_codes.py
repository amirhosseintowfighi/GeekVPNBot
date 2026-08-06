"""Single-use 2FA recovery codes."""

from __future__ import annotations

import pytest

from geekvpn.infrastructure.security.recovery_codes import (
    ALPHABET,
    CODE_COUNT,
    RecoveryCodeError,
    consume,
    generate,
    hash_code,
    normalise,
    should_regenerate,
)


class TestGeneration:
    def test_a_full_set_is_issued(self):
        assert len(generate().plaintext) == CODE_COUNT
        assert len(generate().hashes) == CODE_COUNT

    def test_codes_are_unique_within_a_set(self):
        issued = generate(50)
        assert len(set(issued.plaintext)) == 50

    def test_codes_avoid_visually_ambiguous_characters(self):
        """These are read off paper under stress; O/0 and I/1 cause failures."""
        for forbidden in ("O", "0", "I", "1", "L", "U"):
            assert forbidden not in ALPHABET

    def test_the_hash_never_contains_the_code(self):
        issued = generate(1)
        body = issued.plaintext[0].replace("-", "")
        assert body not in issued.hashes[0]

    def test_two_sets_do_not_overlap(self):
        assert set(generate().plaintext).isdisjoint(generate().plaintext)

    def test_the_same_code_hashed_twice_gives_different_stored_values(self):
        """A per-code salt: identical codes must not be spottable in the table."""
        assert hash_code("ABCD-EFGH") != hash_code("ABCD-EFGH")

    def test_an_empty_set_is_refused(self):
        with pytest.raises(ValueError):
            generate(0)


class TestTypingTolerance:
    def test_case_and_separators_are_forgiven(self):
        issued = generate(1)
        sloppy = issued.plaintext[0].lower().replace("-", " ")
        assert consume(issued.hashes, sloppy).accepted

    def test_no_separator_at_all_is_accepted(self):
        issued = generate(1)
        assert consume(issued.hashes, issued.plaintext[0].replace("-", "")).accepted

    def test_transcription_confusions_are_mapped(self):
        """Someone who reads O for Q must still get in."""
        assert normalise("OOOO-IIII") == normalise("QQQQ-JJJJ")


class TestSingleUse:
    def test_a_used_code_is_removed(self):
        issued = generate()
        result = consume(issued.hashes, issued.plaintext[0])
        assert result.accepted
        assert result.remaining_count == CODE_COUNT - 1

    def test_a_code_cannot_be_used_twice(self):
        """A reusable recovery code is just a weak second password."""
        issued = generate()
        first = consume(issued.hashes, issued.plaintext[0])
        assert not consume(first.remaining, issued.plaintext[0]).accepted

    def test_using_one_code_does_not_invalidate_the_others(self):
        issued = generate()
        remaining = consume(issued.hashes, issued.plaintext[0]).remaining
        assert consume(remaining, issued.plaintext[5]).accepted

    def test_a_wrong_code_changes_nothing(self):
        issued = generate()
        result = consume(issued.hashes, "ZZZZ-ZZZZ")
        assert not result.accepted
        assert result.remaining_count == CODE_COUNT

    def test_an_empty_answer_is_refused_without_consuming_anything(self):
        issued = generate()
        result = consume(issued.hashes, "   ")
        assert not result.accepted
        assert result.remaining_count == CODE_COUNT

    def test_a_corrupt_stored_hash_raises_rather_than_admitting_anyone(self):
        """Treating an unreadable hash as a match would be a total bypass."""
        with pytest.raises(RecoveryCodeError):
            consume(("not-a-hash",), "ABCD-EFGH")

    def test_the_last_code_still_works(self):
        issued = generate()
        remaining = issued.hashes
        for code in issued.plaintext[:-1]:
            remaining = consume(remaining, code).remaining
        assert consume(remaining, issued.plaintext[-1]).accepted


class TestRegenerationNag:
    def test_a_low_set_prompts_a_reprint(self):
        assert should_regenerate(2) is True
        assert should_regenerate(0) is True

    def test_a_full_set_does_not(self):
        assert should_regenerate(CODE_COUNT) is False
