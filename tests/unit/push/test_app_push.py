"""App push: the service-account parser and the support-reply hook."""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace

from geekvpn.application.notifications.subscribers import EngineSupportNotifier
from geekvpn.infrastructure.push.fcm import ServiceAccount
from tests.unit.notifications.fakes import USER_ID
from tests.unit.notifications.world import World

_KEY = {
    "type": "service_account",
    "project_id": "geek-test",
    "client_email": "push@geek-test.iam.gserviceaccount.com",
    "private_key": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n",
}


def test_a_service_account_parses_from_json():
    account = ServiceAccount.parse(json.dumps(_KEY))
    assert account is not None
    assert account.project_id == "geek-test"
    assert account.client_email.startswith("push@")


def test_a_service_account_parses_from_base64():
    raw = base64.b64encode(json.dumps(_KEY).encode()).decode()
    account = ServiceAccount.parse(raw)
    assert account is not None
    assert account.project_id == "geek-test"


def test_anything_else_is_not_a_service_account():
    assert ServiceAccount.parse("") is None
    assert ServiceAccount.parse("not base64 !!") is None
    assert ServiceAccount.parse(json.dumps({"project_id": "x"})) is None


class RecordingPush:
    def __init__(self) -> None:
        self.sent: list[tuple[int, dict[str, str]]] = []

    def notify(self, telegram_id: int, data: dict[str, str]) -> None:
        self.sent.append((telegram_id, data))


def _ticket() -> SimpleNamespace:
    return SimpleNamespace(
        id="0f8fad5bd9cb469fa16570867728950e",
        user_id=USER_ID,
        reference="SUP-1405-000042",
    )


def test_a_support_reply_also_reaches_the_app():
    world = World()
    push = RecordingPush()
    notifier = EngineSupportNotifier(engine=world.engine, app_push=push)

    notifier.notify_customer_reply(_ticket(), "سلام، مشکل حل شد.")

    assert world.telegram.calls == [(USER_ID, "ticket.answered")]
    assert push.sent == [
        (
            USER_ID,
            {
                "type": "ticket",
                "ticket_id": "0f8fad5b-d9cb-469f-a165-70867728950e",
                "reference": "SUP-1405-000042",
                "body": "سلام، مشکل حل شد.",
            },
        )
    ]


def test_a_long_reply_is_cut_for_the_push_only():
    world = World()
    push = RecordingPush()
    EngineSupportNotifier(engine=world.engine, app_push=push).notify_customer_reply(
        _ticket(), "ا" * 5000
    )
    assert len(push.sent[0][1]["body"]) == 400


def test_without_push_configured_only_telegram_is_used():
    world = World()
    EngineSupportNotifier(engine=world.engine).notify_customer_reply(_ticket(), "جواب")
    assert world.telegram.calls == [(USER_ID, "ticket.answered")]
