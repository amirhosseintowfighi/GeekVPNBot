"""Referral code generation.

Alphabet excludes characters that are indistinguishable in Persian UI fonts and
in voice: no O/0, no I/1/L. A referral code gets read aloud and typed by hand.
"""

from __future__ import annotations

import secrets

REFERRAL_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
DEFAULT_LENGTH = 8


def generate_referral_code(*, length: int = DEFAULT_LENGTH) -> str:
    return "".join(secrets.choice(REFERRAL_ALPHABET) for _ in range(length))
