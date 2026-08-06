"""Opaque refresh tokens.

Why opaque rather than a second JWT: a refresh token must be revocable, and a
self-contained token is not. This one is a random 256-bit string whose SHA-256
hash is the primary lookup key - revoking it is a row update.

Why SHA-256 and not Argon2: the token has full entropy, so there is nothing to
brute-force. Key stretching protects human-chosen secrets. Using Argon2 here
would add ~100ms to every refresh and buy nothing.
"""

from __future__ import annotations

import hashlib
import secrets

TOKEN_BYTES = 32  # 256 bits


class Sha256RefreshTokenFactory:
    def generate(self) -> tuple[str, str]:
        plaintext = secrets.token_urlsafe(TOKEN_BYTES)
        return plaintext, self.hash(plaintext)

    def hash(self, plaintext: str) -> str:
        return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
