"""Argon2id password hashing.

Argon2id is the current OWASP recommendation and the winner of the Password
Hashing Competition. bcrypt truncates at 72 bytes and has no memory hardness;
PBKDF2 is cheap on GPUs. Neither is appropriate for an account that can approve
payments.

Parameters follow OWASP's baseline (19 MiB, t=2, p=1) and are tuned upward to
64 MiB here because these hashes are computed on a login endpoint that a human
hits a handful of times a day - not a hot path.

`needs_rehash` exists so raising the parameters later silently upgrades every
admin on their next successful login, with no migration and no forced reset.
"""

from __future__ import annotations

from argon2 import PasswordHasher as Argon2PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MEMORY_COST_KIB = 65_536  # 64 MiB
TIME_COST = 3
PARALLELISM = 4
HASH_LENGTH = 32
SALT_LENGTH = 16


class Argon2Hasher:
    def __init__(self) -> None:
        self._hasher = Argon2PasswordHasher(
            time_cost=TIME_COST,
            memory_cost=MEMORY_COST_KIB,
            parallelism=PARALLELISM,
            hash_len=HASH_LENGTH,
            salt_len=SALT_LENGTH,
        )

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        """Return False on any failure.

        Callers must not be able to tell "wrong password" from "corrupt hash"
        by catching different exceptions - both are simply a failed login.
        """
        try:
            return self._hasher.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(password_hash)
        except InvalidHashError:
            return True
