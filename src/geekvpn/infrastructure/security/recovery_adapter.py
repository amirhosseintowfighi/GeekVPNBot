"""The `RecoveryCodes` port, over `recovery_codes`.

Thin on purpose. The rules - scrypt, single use, constant-time comparison
across every stored hash - live in `recovery_codes` and are tested there; this
only puts them behind the shape the application depends on, so the layer
contract holds.
"""

from __future__ import annotations

from geekvpn.application.ports.passwords import RecoveryOutcome
from geekvpn.infrastructure.security import recovery_codes


class ScryptRecoveryCodes:
    def issue(self, count: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
        issued = recovery_codes.generate(count)
        return issued.plaintext, issued.hashes

    def consume(self, hashes: tuple[str, ...], code: str) -> RecoveryOutcome:
        try:
            result = recovery_codes.consume(hashes, code)
        except recovery_codes.RecoveryCodeError:
            # A hash we cannot parse is a refusal, not a crash: one corrupt row
            # must not lock somebody out of every code they hold.
            return RecoveryOutcome(False, hashes)
        return RecoveryOutcome(result.accepted, result.remaining)


__all__ = ["ScryptRecoveryCodes"]
