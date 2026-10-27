"""Every group and channel id setting must be enterable as a negative number.

Telegram group and channel ids are negative. The admin panel's number box
stripped the minus sign, so the backup channel and all six notification groups
could only ever be saved as positive numbers or 0 - and a backup channel at 0
sends the backup to whoever pressed the button instead. The panel now renders
these as `chat_id`, which it edits as text; this pins that the backend says so,
for every such setting, and accepts the negative value it is then sent.
"""

from __future__ import annotations

import pytest

from geekvpn.application.platform.settings_service import SETTING_REGISTRY

CHAT_IDS = sorted(key for key in SETTING_REGISTRY if key.endswith("chat_id"))


def test_the_backup_channel_and_alert_groups_are_all_covered() -> None:
    assert "backup.chat_id" in CHAT_IDS
    assert len(CHAT_IDS) >= 7


@pytest.mark.parametrize("key", CHAT_IDS)
def test_the_panel_is_told_it_is_a_chat_id(key: str) -> None:
    assert SETTING_REGISTRY[key].kind == "chat_id"


@pytest.mark.parametrize("key", CHAT_IDS)
def test_a_channel_id_is_accepted(key: str) -> None:
    assert SETTING_REGISTRY[key].coerce(-1004423033275) == -1004423033275
