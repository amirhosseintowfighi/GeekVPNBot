"""`BotServiceOwnership`: the rules the bot and the app's endpoints share.

Rename, transfer and the unused-service refund are reached from two places -
the bot's service screen and `/api/miniapp/subscriptions/{id}/...` - and both
call this adapter. These pin the rules that moved into it so the endpoints
could use them: a lone `-` clears a name, a transfer to oneself and to a
stranger are refused with their own types, and an operator report says where
a change came from when it was not the bot.
"""

from __future__ import annotations

import pytest

from geekvpn.application.platform.settings_service import (
    REFUND_WINDOW_HOURS,
    RENAME_ENABLED,
    TRANSFER_ENABLED,
)
from geekvpn.domain.provisioning.errors import (
    RefundDisabled,
    ServiceNameTooLong,
    TransferToSelf,
)
from geekvpn.infrastructure.bot.ownership import RecipientNotFound, ServiceDisabled
from tests.unit.bot.ownership_fakes import FRIEND_TG, OWNER_TG, World

pytestmark = pytest.mark.unit


# -- rename ----------------------------------------------------------------------


async def test_a_lone_dash_clears_the_name_as_the_bot_always_did() -> None:
    world = World()
    sub = await world.service()
    sub.rename("گوشی من")

    card = await world.ownership.rename(world.owner.id, world.sub_id, name=" - ")

    assert card.display_name is None


async def test_a_name_is_trimmed_and_squeezed() -> None:
    world = World()
    await world.service()

    card = await world.ownership.rename(world.owner.id, world.sub_id, name="  گوشی   مامان ")

    assert card.display_name == "گوشی مامان"


async def test_a_name_too_long_is_refused_with_its_own_code() -> None:
    world = World()
    await world.service()

    with pytest.raises(ServiceNameTooLong) as caught:
        await world.ownership.rename(world.owner.id, world.sub_id, name="x" * 33)
    assert caught.value.code == "service_name_too_long"


async def test_renaming_follows_the_shops_switch() -> None:
    world = World(settings={RENAME_ENABLED.key: False})
    await world.service()

    with pytest.raises(ServiceDisabled):
        await world.ownership.rename(world.owner.id, world.sub_id, name="x")


async def test_nobody_renames_a_service_that_is_not_theirs() -> None:
    world = World()
    await world.service()

    with pytest.raises(LookupError):
        await world.ownership.rename(world.friend.id, world.sub_id, name="mine now")


async def test_a_report_names_the_app_only_when_the_app_made_the_change() -> None:
    world = World()
    await world.service()

    await world.ownership.rename(world.owner.id, world.sub_id, name="یک")
    await world.ownership.rename(world.owner.id, world.sub_id, name="دو", origin_fa="اپ")

    from_bot, from_app = world.sync.reports
    assert "از طریق" not in from_bot
    assert from_app.endswith("از طریق: اپ")


# -- transfer --------------------------------------------------------------------


async def test_a_transfer_moves_the_service_and_tells_the_recipient() -> None:
    world = World()
    sub = await world.service()

    await world.ownership.transfer(world.owner.id, world.sub_id, to_telegram_id=FRIEND_TG)

    assert sub.user_id == FRIEND_TG
    assert world.sync.dispatched == [FRIEND_TG]
    assert len(world.sync.reports) == 1


async def test_a_transfer_to_its_own_owner_is_refused_before_anything_moves() -> None:
    world = World()
    await world.service()

    with pytest.raises(TransferToSelf):
        await world.ownership.transfer(world.owner.id, world.sub_id, to_telegram_id=OWNER_TG)
    assert world.sync.dispatched == []


async def test_a_recipient_who_never_started_the_bot_is_its_own_refusal() -> None:
    """Still a LookupError, which is what the bot's handler catches."""
    world = World()
    await world.service()

    with pytest.raises(RecipientNotFound) as caught:
        await world.ownership.transfer(world.owner.id, world.sub_id, to_telegram_id=31337)
    assert isinstance(caught.value, LookupError)


async def test_transfers_follow_the_shops_switch() -> None:
    world = World(settings={TRANSFER_ENABLED.key: False})
    await world.service()

    with pytest.raises(ServiceDisabled):
        await world.ownership.transfer(world.owner.id, world.sub_id, to_telegram_id=FRIEND_TG)


# -- refund ----------------------------------------------------------------------


async def test_the_quote_is_what_the_refund_then_pays() -> None:
    world = World(settings={REFUND_WINDOW_HOURS.key: 24})
    await world.service()

    quote = await world.ownership.refund_quote(world.owner.id, world.sub_id)
    paid = await world.ownership.refund_unused(world.owner.id, world.sub_id, origin_fa="اپ")

    assert quote.amount.amount == paid == 200_000
    assert world.sync.reports[-1].endswith("از طریق: اپ")


async def test_a_shop_without_refunds_says_so_in_the_quote() -> None:
    world = World()
    await world.service()

    with pytest.raises(RefundDisabled):
        await world.ownership.refund_quote(world.owner.id, world.sub_id)
