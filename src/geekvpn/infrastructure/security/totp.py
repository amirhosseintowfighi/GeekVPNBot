"""RFC 6238 TOTP, implemented on the standard library.

Why not a dependency: TOTP is forty lines of HMAC. Adding a package to the
supply chain of the admin login for forty lines is a bad trade, and every line
here is directly testable against the RFC's published vectors.

Security details that matter:
* verification uses `hmac.compare_digest`, so a code cannot be guessed by
  timing;
* a +/-1 step window absorbs clock skew, and nothing wider - each extra step
  linearly multiplies an attacker's chance;
* the caller is responsible for replay protection (see
  `presentation/api/routers/admin_auth.py`), because a code stays valid for its
  whole 30-second step.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

DIGITS = 6
STEP_SECONDS = 30
WINDOW_STEPS = 1
SECRET_BYTES = 20  # 160 bits, per RFC 4226


class Rfc6238TotpService:
    def __init__(
        self,
        *,
        digits: int = DIGITS,
        step_seconds: int = STEP_SECONDS,
        window_steps: int = WINDOW_STEPS,
    ) -> None:
        self._digits = digits
        self._step = step_seconds
        self._window = window_steps

    def generate_secret(self) -> str:
        """Base32, unpadded - what authenticator apps expect."""
        return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode("ascii").rstrip("=")

    def provisioning_uri(self, *, secret: str, account: str, issuer: str) -> str:
        label = quote(f"{issuer}:{account}", safe="")
        params = urlencode(
            {
                "secret": secret,
                "issuer": issuer,
                "algorithm": "SHA1",
                "digits": self._digits,
                "period": self._step,
            }
        )
        return f"otpauth://totp/{label}?{params}"

    def code_at(self, *, secret: str, timestamp: float) -> str:
        return self._code_for_counter(secret, int(timestamp) // self._step)

    def verify(self, *, secret: str, code: str, now: float | None = None) -> bool:
        candidate = code.strip().replace(" ", "")
        if not candidate.isdigit() or len(candidate) != self._digits:
            return False

        counter = int(now if now is not None else time.time()) // self._step
        for offset in range(-self._window, self._window + 1):
            expected = self._code_for_counter(secret, counter + offset)
            if hmac.compare_digest(expected, candidate):
                return True
        return False

    def _code_for_counter(self, secret: str, counter: int) -> str:
        key = _decode_base32(secret)
        digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFF_FFFF
        return str(truncated % (10**self._digits)).zfill(self._digits)


def _decode_base32(secret: str) -> bytes:
    normalised = secret.strip().replace(" ", "").upper()
    padding = "=" * (-len(normalised) % 8)
    try:
        return base64.b32decode(normalised + padding, casefold=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid base32 TOTP secret.") from exc
