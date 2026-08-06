"""A challenge a human can answer and a script finds inconvenient.

Why not reCAPTCHA or hCaptcha
-----------------------------
The primary surface here is a Telegram bot. A bot conversation cannot render a
third-party JavaScript widget, and both major providers are awkward-to-blocked
from Iranian networks, so a hosted captcha would fail exactly the users it is
meant to protect. The Mini App *could* host a widget, and so the store and the
challenge sit behind small interfaces: a hosted provider can be added later
without touching the callers.

An honest statement of strength
-------------------------------
Arithmetic in Persian words stops naive scripted abuse: credential stuffing
lists, replayed sign-up floods, someone hammering a login form. It does **not**
stop a determined attacker who reads the question, and it is not claimed to.
It buys time and raises cost; the lockout in ``throttling.py`` is what actually
stops patient guessing.
"""

from __future__ import annotations

import enum
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Protocol, runtime_checkable

#: Long enough to read a question and type an answer on a phone, short enough
#: that a harvested challenge is stale before it can be farmed out.
TTL_SECONDS: Final = 180

#: A wrong answer three times means a new challenge, not endless guessing at one.
#: With answers in 0..40 an unlimited-attempt challenge is worth nothing.
MAX_ATTEMPTS: Final = 3

_FA_DIGITS: Final = "۰۱۲۳۴۵۶۷۸۹"
_AR_DIGITS: Final = "٠١٢٣٤٥٦٧٨٩"
_DIGIT_FOLD: Final = {ord(c): str(i) for i, c in enumerate(_FA_DIGITS)} | {
    ord(c): str(i) for i, c in enumerate(_AR_DIGITS)
}

#: Numbers as words, not digits. A digit-scraping regex solves "3 + 4"; it does
#: not solve "سه به علاوه کهار" without a Persian number parser.
_WORDS_FA: Final = (
    "صفر",
    "یک",
    "دو",
    "سه",
    "چهار",
    "پنج",
    "شش",
    "هفت",
    "هشت",
    "نه",
    "ده",
    "یازده",
    "دوازده",
    "سیزده",
    "چهارده",
    "پانزده",
    "شانزده",
    "هفده",
    "هجده",
    "نوزده",
    "بیست",
)


class ChallengeKind(enum.StrEnum):
    SUM = "sum"
    DIFFERENCE = "difference"
    #: "which of these is the largest" - different enough that a solver tuned
    #: for arithmetic misses it.
    LARGEST = "largest"


class CaptchaError(Exception):
    """Base class for captcha failures."""


@dataclass(frozen=True, slots=True)
class Challenge:
    """One issued puzzle.

    ``answer`` is held in plain text. That is deliberate and not an oversight:
    the answer is a number below fifty, so hashing it would be defeated by
    trying fifty inputs, and the value never leaves the server. Storing a hash
    here would look more secure while being exactly as weak, and pretending
    otherwise in a security review is worse than the plain integer.
    """

    challenge_id: str
    kind: ChallengeKind
    question_fa: str
    answer: int
    issued_at: datetime
    attempts: int = 0

    @property
    def expires_at(self) -> datetime:
        return self.issued_at + timedelta(seconds=TTL_SECONDS)

    def is_expired(self, *, now: datetime) -> bool:
        return now >= self.expires_at

    def is_exhausted(self) -> bool:
        return self.attempts >= MAX_ATTEMPTS

    def with_attempt(self) -> Challenge:
        return Challenge(
            challenge_id=self.challenge_id,
            kind=self.kind,
            question_fa=self.question_fa,
            answer=self.answer,
            issued_at=self.issued_at,
            attempts=self.attempts + 1,
        )


class Outcome(enum.StrEnum):
    SOLVED = "solved"
    WRONG = "wrong"
    EXPIRED = "expired"
    EXHAUSTED = "exhausted"
    MALFORMED = "malformed"


@dataclass(frozen=True, slots=True)
class Verdict:
    outcome: Outcome
    message_fa: str
    #: The challenge with its attempt counter advanced, or ``None`` when the
    #: caller must issue a fresh one.
    challenge: Challenge | None

    @property
    def solved(self) -> bool:
        return self.outcome is Outcome.SOLVED

    @property
    def needs_new_challenge(self) -> bool:
        return self.outcome in (Outcome.EXPIRED, Outcome.EXHAUSTED)


_MESSAGES_FA: Final[dict[Outcome, str]] = {
    Outcome.SOLVED: "تأیید شد.",
    Outcome.WRONG: "پاسخ نادرست است. دوباره تلاش کنید.",
    Outcome.EXPIRED: "زمان پاسخ تمام شد. پرسش تازه‌ای بگیرید.",
    Outcome.EXHAUSTED: "تعداد تلاش‌ها بیش از حد مجاز بود. پرسش تازه‌ای بگیرید.",
    Outcome.MALFORMED: "لطفاً پاسخ را فقط به عدد بنویسید.",
}


def _word(number: int) -> str:
    return _WORDS_FA[number] if number < len(_WORDS_FA) else str(number)


def normalise_answer(raw: str) -> int | None:
    """Read a human's answer, or ``None`` if it is not a number.

    Persian and Arabic-Indic digits are folded, Arabic-Indic and Persian
    thousands separators and spaces are dropped, and a leading plus is
    tolerated. A customer typing ۷ must not be told they answered wrongly
    because their keyboard is Persian - that is the single most likely way a
    captcha locks out the very users it should let through.
    """
    if raw is None:
        return None
    text = raw.strip().translate(_DIGIT_FOLD)
    for junk in (",", "،", "٬", " ", "\u200c", "\u200f", "\u200e", "+"):
        text = text.replace(junk, "")
    if not text or not text.isdigit():
        return None
    return int(text)


def generate(*, now: datetime, challenge_id: str | None = None) -> Challenge:
    """Issue a fresh challenge.

    Uses ``secrets`` rather than ``random``: a predictable sequence of puzzles is
    a captcha that can be pre-solved.
    """
    kind = secrets.choice(tuple(ChallengeKind))
    identifier = challenge_id or secrets.token_urlsafe(12)

    if kind is ChallengeKind.SUM:
        left, right = secrets.randbelow(9) + 1, secrets.randbelow(9) + 1
        question = f"حاصل جمع {_word(left)} به علاوه {_word(right)} چند است؟"
        answer = left + right
    elif kind is ChallengeKind.DIFFERENCE:
        left = secrets.randbelow(10) + 10
        right = secrets.randbelow(9) + 1
        # Ordered so the answer is never negative: a captcha that expects "منفی
        # دو" from a numeric keypad is a bug, not a test of humanity.
        question = f"{_word(left)} منهای {_word(right)} چند است؟"
        answer = left - right
    else:
        pool: list[int] = []
        while len(pool) < 3:
            candidate = secrets.randbelow(20) + 1
            if candidate not in pool:
                pool.append(candidate)
        shown = "، ".join(_word(value) for value in pool)
        question = f"بزرگ‌ترین عدد را بنویسید: {shown}"
        answer = max(pool)

    return Challenge(
        challenge_id=identifier,
        kind=kind,
        question_fa=question,
        answer=answer,
        issued_at=now,
    )


def verify(challenge: Challenge, raw_answer: str, *, now: datetime) -> Verdict:
    """Check an answer. Expiry and exhaustion are checked before correctness.

    Order matters: checking correctness first would let an expired challenge be
    solved, which is how a harvested-and-shared puzzle stays useful forever.
    """
    if challenge.is_expired(now=now):
        return Verdict(Outcome.EXPIRED, _MESSAGES_FA[Outcome.EXPIRED], None)
    if challenge.is_exhausted():
        return Verdict(Outcome.EXHAUSTED, _MESSAGES_FA[Outcome.EXHAUSTED], None)

    parsed = normalise_answer(raw_answer)
    if parsed is None:
        advanced = challenge.with_attempt()
        outcome = Outcome.EXHAUSTED if advanced.is_exhausted() else Outcome.MALFORMED
        # A malformed answer still burns an attempt. Otherwise "send garbage
        # forever" is a free way to keep one challenge alive indefinitely.
        return Verdict(
            outcome,
            _MESSAGES_FA[outcome],
            None if advanced.is_exhausted() else advanced,
        )

    if parsed == challenge.answer:
        return Verdict(Outcome.SOLVED, _MESSAGES_FA[Outcome.SOLVED], None)

    advanced = challenge.with_attempt()
    if advanced.is_exhausted():
        return Verdict(Outcome.EXHAUSTED, _MESSAGES_FA[Outcome.EXHAUSTED], None)
    return Verdict(Outcome.WRONG, _MESSAGES_FA[Outcome.WRONG], advanced)


@runtime_checkable
class CaptchaStore(Protocol):
    """Where issued challenges live between two requests.

    Deliberately tiny so that the Redis implementation, an in-memory test
    double, and a future hosted provider are interchangeable.
    """

    def put(self, challenge: Challenge, *, ttl_seconds: int = TTL_SECONDS) -> None: ...

    def get(self, challenge_id: str) -> Challenge | None: ...

    def delete(self, challenge_id: str) -> None: ...


__all__ = [
    "MAX_ATTEMPTS",
    "TTL_SECONDS",
    "CaptchaError",
    "CaptchaStore",
    "Challenge",
    "ChallengeKind",
    "Outcome",
    "Verdict",
    "generate",
    "normalise_answer",
    "verify",
]
