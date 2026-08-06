"""In-memory doubles for the payment ports.

Plain classes rather than mocks. A mock asserts that a method was called; a
fake lets the test assert on the resulting *balance*, which is the thing that
actually matters when money is involved.

``FakeClock`` is manual on purpose. Payments are full of windows and expiries,
and a test that cannot move time cannot test them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count

from geekvpn.domain.payments.enums import PaymentState, TransactionKind
from geekvpn.domain.payments.errors import PaymentNotFound

EPOCH = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, now: datetime = EPOCH) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


class FakeIds:
    """Predictable ids so assertions can name them."""

    def __init__(self, prefix: str = "id") -> None:
        self._prefix = prefix
        self._counter = count(1)

    def new_id(self) -> str:
        return f"{self._prefix}-{next(self._counter)}"


class FakeEvents:
    def __init__(self) -> None:
        self.published: list[object] = []

    def publish_all(self, events) -> None:
        self.published.extend(events)

    def names(self) -> list[str]:
        return [type(event).__name__ for event in self.published]

    def of(self, name: str) -> list[object]:
        return [e for e in self.published if type(e).__name__ == name]


class FakeAudit:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, *, action, actor_id, payment_id=None, details=None) -> None:
        self.entries.append(
            {
                "action": action,
                "actor_id": actor_id,
                "payment_id": payment_id,
                "details": details or {},
            }
        )

    def actions(self) -> list[str]:
        return [entry["action"] for entry in self.entries]


class FakeWallets:
    def __init__(self) -> None:
        self.wallets: dict[int, object] = {}

    def get_or_create(self, user_id: int):
        from geekvpn.domain.payments.wallet import Wallet

        if user_id not in self.wallets:
            self.wallets[user_id] = Wallet(user_id)
        return self.wallets[user_id]

    def save(self, wallet) -> None:
        self.wallets[wallet.id] = wallet

    def history(self, user_id, *, kind=None, limit=20, offset=0):
        wallet = self.get_or_create(user_id)
        entries = wallet.history(kind=kind)
        return entries[offset : offset + limit]

    def count_history(self, user_id, *, kind=None) -> int:
        return len(self.get_or_create(user_id).history(kind=kind))


class FakePayments:
    def __init__(self) -> None:
        self.rows: dict[str, object] = {}

    def get(self, payment_id: str):
        try:
            return self.rows[payment_id]
        except KeyError as error:
            raise PaymentNotFound(payment_id=payment_id) from error

    def save(self, payment) -> None:
        self.rows[payment.id] = payment

    def find_by_digest(self, digest: str):
        for payment in self.rows.values():
            proof = getattr(payment, "proof", None)
            if proof is not None and proof.digest == digest:
                return payment
        return None

    def find_by_gateway_reference(self, *, gateway_key: str, reference: str):
        for payment in self.rows.values():
            if payment.gateway_key == gateway_key and payment.gateway_reference == reference:
                return payment
        return None

    def pending_for_user(self, user_id: int):
        return [p for p in self.rows.values() if p.user_id == user_id and not p.state.is_terminal()]

    def in_state(self, state: PaymentState, *, limit: int = 100):
        return [p for p in self.rows.values() if p.state is state][:limit]

    def expiring_before(self, moment):
        return [
            p
            for p in self.rows.values()
            if p.expires_at is not None and p.expires_at <= moment and not p.state.is_terminal()
        ]


class FakeInvoices:
    def __init__(self) -> None:
        self.rows: dict[str, object] = {}
        self._sequences: dict[int, int] = {}

    def get(self, invoice_id: str):
        return self.rows[invoice_id]

    def save(self, invoice) -> None:
        self.rows[invoice.id] = invoice

    def for_user(self, user_id, *, limit=20, offset=0):
        rows = [i for i in self.rows.values() if i.user_id == user_id]
        return rows[offset : offset + limit]

    def next_sequence(self, *, year: int) -> int:
        self._sequences[year] = self._sequences.get(year, 0) + 1
        return self._sequences[year]


class FakeStorage:
    """Receipt storage that keeps bytes in a dict."""

    def __init__(self) -> None:
        self.saved: dict[str, bytes] = {}
        self._counter = count(1)

    def store(self, *, payment_id: str, content: bytes, mime_type: str) -> str:
        locator = f"receipt-{next(self._counter)}"
        self.saved[locator] = content
        return locator

    def url_for(self, locator: str) -> str:
        return f"https://files.invalid/{locator}"


__all__ = [
    "EPOCH",
    "FakeAudit",
    "FakeClock",
    "FakeEvents",
    "FakeIds",
    "FakeInvoices",
    "FakePayments",
    "FakeStorage",
    "FakeWallets",
    "TransactionKind",
]
