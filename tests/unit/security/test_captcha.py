"""Captcha challenge behaviour."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from geekvpn.infrastructure.security import captcha
from geekvpn.infrastructure.security.captcha import (
    MAX_ATTEMPTS,
    TTL_SECONDS,
    Challenge,
    ChallengeKind,
    Outcome,
    generate,
    normalise_answer,
    verify,
)

NOW = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)


def fixed(answer: int = 7, *, attempts: int = 0, issued_at: datetime = NOW) -> Challenge:
    return Challenge(
        challenge_id="c1",
        kind=ChallengeKind.SUM,
        question_fa="حاصل جمع سه به علاوه چهار چند است؟",
        answer=answer,
        issued_at=issued_at,
        attempts=attempts,
    )


class TestGeneration:
    def test_questions_are_in_persian_words_not_digits(self):
        """A digit-scraping regex must not be able to read the operands."""
        for _ in range(20):
            challenge = generate(now=NOW)
            if challenge.kind is not ChallengeKind.LARGEST:
                assert not any(character.isdigit() for character in challenge.question_fa)

    def test_the_answer_is_never_negative(self):
        """A numeric keypad cannot type a minus sign."""
        for _ in range(50):
            assert generate(now=NOW).answer >= 0

    def test_challenges_are_not_predictable(self):
        """A fixed sequence of puzzles can be pre-solved once and replayed."""
        questions = {generate(now=NOW).question_fa for _ in range(30)}
        assert len(questions) > 5

    def test_identifiers_are_unique(self):
        identifiers = {generate(now=NOW).challenge_id for _ in range(50)}
        assert len(identifiers) == 50

    def test_every_kind_can_be_produced_and_solved(self):
        seen = set()
        for _ in range(200):
            challenge = generate(now=NOW)
            seen.add(challenge.kind)
            assert verify(challenge, str(challenge.answer), now=NOW).solved
        assert seen == set(ChallengeKind)


class TestPersianInput:
    def test_persian_digits_are_accepted(self):
        """The most likely way a captcha locks out the users it should admit."""
        assert normalise_answer("۱۲") == 12

    def test_arabic_indic_digits_are_accepted(self):
        assert normalise_answer("١٢") == 12

    def test_surrounding_whitespace_and_direction_marks_are_forgiven(self):
        assert normalise_answer("  \u200f۷ ") == 7

    def test_words_are_not_accepted_as_a_number(self):
        assert normalise_answer("هفت") is None
        assert normalise_answer("") is None
        assert normalise_answer("12a") is None

    def test_a_persian_answer_solves_a_challenge(self):
        assert verify(fixed(7), "۷", now=NOW).solved


class TestVerification:
    def test_a_correct_answer_solves_it(self):
        assert verify(fixed(7), "7", now=NOW).outcome is Outcome.SOLVED

    def test_a_wrong_answer_burns_one_attempt(self):
        verdict = verify(fixed(7), "8", now=NOW)
        assert verdict.outcome is Outcome.WRONG
        assert verdict.challenge is not None
        assert verdict.challenge.attempts == 1

    def test_attempts_are_finite(self):
        """With answers under fifty, unlimited attempts is no protection at all."""
        verdict = verify(fixed(7, attempts=MAX_ATTEMPTS - 1), "8", now=NOW)
        assert verdict.outcome is Outcome.EXHAUSTED
        assert verdict.needs_new_challenge

    def test_garbage_also_burns_an_attempt(self):
        """Otherwise sending nonsense forever keeps one challenge alive."""
        verdict = verify(fixed(7), "???", now=NOW)
        assert verdict.outcome is Outcome.MALFORMED
        assert verdict.challenge is not None
        assert verdict.challenge.attempts == 1

    def test_an_expired_challenge_cannot_be_solved_even_with_the_right_answer(self):
        """Otherwise a harvested puzzle stays useful forever."""
        later = NOW + timedelta(seconds=TTL_SECONDS + 1)
        verdict = verify(fixed(7), "7", now=later)
        assert verdict.outcome is Outcome.EXPIRED
        assert not verdict.solved

    def test_expiry_is_checked_before_correctness(self):
        expired = fixed(7, issued_at=NOW - timedelta(seconds=TTL_SECONDS + 60))
        assert verify(expired, "7", now=NOW).outcome is Outcome.EXPIRED

    def test_an_exhausted_challenge_is_refused_before_correctness(self):
        exhausted = fixed(7, attempts=MAX_ATTEMPTS)
        assert verify(exhausted, "7", now=NOW).outcome is Outcome.EXHAUSTED

    def test_every_outcome_carries_a_persian_message(self):
        """An English error in a Persian bot is a support ticket."""
        for outcome in Outcome:
            message = captcha._MESSAGES_FA[outcome]
            assert message
            assert not message.isascii()
