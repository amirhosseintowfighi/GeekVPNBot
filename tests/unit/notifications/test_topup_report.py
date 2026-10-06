"""A settled top-up reaches the payments chat, whichever way it settled."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from geekvpn.application.notifications.operator_alerts import AlertKind, OperatorReports

pytestmark = pytest.mark.unit


class _Sender:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    def send_text(self, *, chat_id: int, text: str, buttons: object) -> None:
        self.sent.append((chat_id, text))


def _reports() -> tuple[OperatorReports, _Sender, list[AlertKind]]:
    sender = _Sender()
    routed: list[AlertKind] = []

    def route(kind: AlertKind) -> int:
        routed.append(kind)
        return -100

    reports = OperatorReports(
        sender=sender,  # type: ignore[arg-type]
        directory=SimpleNamespace(operator_chat_ids=lambda: []),  # type: ignore[arg-type]
        route=route,
    )
    return reports, sender, routed


def _credited(kind: str) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=42, amount=500_000, balance_after=650_000, kind=kind, reference="1405-0009"
    )


def test_a_topup_is_reported_to_the_payments_chat() -> None:
    reports, sender, routed = _reports()

    reports.on_wallet_credited(_credited("topup"))

    assert routed == [AlertKind.PAYMENT]
    (chat, text), = sender.sent
    assert chat == -100
    assert "500,000" in text and "<code>42</code>" in text and "1405-0009" in text


@pytest.mark.parametrize("kind", ["cashback", "refund", "transfer_in", "referral_reward"])
def test_other_credits_are_not_reported_as_topups(kind: str) -> None:
    reports, sender, _ = _reports()

    reports.on_wallet_credited(_credited(kind))

    assert sender.sent == []
