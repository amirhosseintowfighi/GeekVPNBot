"""Argon2id adapter.

Deliberately slow (that is the algorithm doing its job), so this file stays
small and every other test uses a fake hasher.
"""

from __future__ import annotations

import pytest

from geekvpn.infrastructure.security.passwords import Argon2Hasher

PASSWORD = "a-long-enough-admin-password"


@pytest.fixture(scope="module")
def hasher():
    return Argon2Hasher()


def test_a_hash_verifies(hasher):
    assert hasher.verify(PASSWORD, hasher.hash(PASSWORD))


def test_a_wrong_password_does_not_verify(hasher):
    assert not hasher.verify("wrong", hasher.hash(PASSWORD))


def test_hashes_are_salted(hasher):
    assert hasher.hash(PASSWORD) != hasher.hash(PASSWORD)


def test_the_hash_is_argon2id(hasher):
    assert hasher.hash(PASSWORD).startswith("$argon2id$")


def test_the_plaintext_never_appears_in_the_hash(hasher):
    assert PASSWORD not in hasher.hash(PASSWORD)


def test_a_corrupt_hash_returns_false_rather_than_raising(hasher):
    """A malformed stored hash must be a failed login, not a 500."""
    assert not hasher.verify(PASSWORD, "not-a-hash")
