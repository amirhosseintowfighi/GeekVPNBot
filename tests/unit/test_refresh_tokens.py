"""Opaque refresh token generation."""

from __future__ import annotations

import hashlib

from geekvpn.infrastructure.security.refresh_tokens import Sha256RefreshTokenFactory


def test_generated_tokens_are_unique():
    factory = Sha256RefreshTokenFactory()
    assert len({factory.generate()[0] for _ in range(500)}) == 500


def test_the_stored_hash_is_sha256_of_the_plaintext():
    plaintext, digest = Sha256RefreshTokenFactory().generate()
    assert digest == hashlib.sha256(plaintext.encode()).hexdigest()


def test_hashing_is_deterministic():
    factory = Sha256RefreshTokenFactory()
    assert factory.hash("abc") == factory.hash("abc")


def test_tokens_carry_at_least_256_bits():
    plaintext, _ = Sha256RefreshTokenFactory().generate()
    assert len(plaintext) >= 43  # base64url of 32 bytes
