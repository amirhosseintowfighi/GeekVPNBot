"""Stickers decorate a screen; they never decide whether it opens.

A sticker is addressed by a `file_id` Telegram issues, so none can be written
down in advance. The pack is read once by name and each section matched to the
sticker whose own emoji fits it - which means a renamed pack, a deleted one, or
a network blip must cost a decoration and nothing else.
"""

from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest

from geekvpn.presentation.bot.ui.stickers import SECTION_EMOJI, StickerBook, send

pytestmark = pytest.mark.unit


class Bot:
    def __init__(self, emoji: list[str] | None = None, *, breaks: bool = False) -> None:
        self.sent: list[str] = []
        self.fetches = 0
        self._emoji = emoji if emoji is not None else ["🛒", "💰", "👋"]
        self._breaks = breaks

    async def get_sticker_set(self, name: str) -> SimpleNamespace:
        self.fetches += 1
        if self._breaks:
            raise RuntimeError("no such set")
        return SimpleNamespace(
            stickers=[
                SimpleNamespace(emoji=emoji, file_id=f"file-{emoji}") for emoji in self._emoji
            ]
        )

    async def send_sticker(self, chat_id: int, file_id: str) -> None:
        self.sent.append(file_id)


async def test_a_section_gets_the_sticker_matching_its_emoji() -> None:
    bot = Bot()

    assert await StickerBook("Pack").for_section(bot, "shop") == "file-🛒"


async def test_the_pack_is_read_once_not_per_screen() -> None:
    """A round trip to Telegram in front of a customer, for decoration."""
    bot = Bot()
    book = StickerBook("Pack")

    await book.for_section(bot, "shop")
    await book.for_section(bot, "wallet")
    await book.for_section(bot, "welcome")

    assert bot.fetches == 1


async def test_a_pack_without_the_emoji_yields_nothing() -> None:
    """And the screen still opens. A bot that refuses to show a price because
    a duck is missing is worse than a price with no duck."""
    bot = Bot(emoji=["🐟"])

    assert await StickerBook("Pack").for_section(bot, "shop") is None


async def test_a_missing_pack_is_not_retried_forever() -> None:
    """A wrong name would otherwise be one failed Telegram call per screen."""
    bot = Bot(breaks=True)
    book = StickerBook("Gone")

    await book.for_section(bot, "shop")
    await book.for_section(bot, "shop")

    assert bot.fetches == 1


async def test_stickers_can_be_turned_off_entirely() -> None:
    bot = Bot()

    assert await StickerBook("").for_section(bot, "shop") is None
    assert bot.fetches == 0


async def test_sending_never_raises() -> None:
    """It is called before the screen it decorates."""
    await send(Bot(breaks=True), 1, StickerBook("Gone"), "shop")
    await send(None, 1, StickerBook("Pack"), "shop")
    await send(Bot(), 1, None, "shop")


async def test_a_later_choice_is_used_when_the_earlier_ones_are_absent() -> None:
    """Packs disagree about which emoji they cover.

    A money duck is the shop's last resort rather than its second choice, but
    it stays in the list: an odd sticker beats a bare screen.
    """
    bot = Bot(emoji=["🤑"])

    assert await StickerBook("Pack").for_section(bot, "shop") == "file-🤑"


def test_every_section_offers_a_fallback() -> None:
    """One emoji is one chance for a pack to not have it."""
    for section, candidates in SECTION_EMOJI.items():
        assert len(candidates) >= 2, section


async def test_a_pack_covering_only_the_common_emoji_still_reaches_every_screen() -> None:
    """UtyaDuck had none of the status or profile emoji, so those two screens
    opened bare while the other eight were decorated.

    The tail of each list is an emoji some other section proved the pack has -
    a shared sticker beats a blank screen, and the first choices still win
    wherever a pack covers them.
    """
    bot = Bot(emoji=["👋", "🛒", "😎", "💰", "🎁", "🤔", "🤓", "🎉"])
    book = StickerBook("Pack")

    for section in SECTION_EMOJI:
        assert await book.for_section(bot, section) is not None, section


async def test_the_first_choice_still_wins_when_it_exists() -> None:
    """The fallbacks must not quietly take over a pack that has the right one."""
    bot = Bot(emoji=["👀", "😎"])

    assert await StickerBook("Pack").for_section(bot, "status") == "file-👀"


async def test_the_shop_does_not_reach_for_a_money_sticker_first() -> None:
    """UtyaDuck has no 🛒, so the shop fell through to 🤑 - a duck with dollar
    signs for eyes, on the screen where a customer decides whether to trust us
    with their money.

    Money emoji stay in the list as a last resort, behind every friendly one,
    because a shop with no sticker is worse than an odd sticker. But they must
    not be the first thing reached for.
    """
    friendly = {"🤩", "😍", "😎", "👍"}
    money = {"🤑", "💸", "💰"}
    order = SECTION_EMOJI["shop"]

    first_money = next((i for i, e in enumerate(order) if e in money), len(order))
    last_friendly = max(
        (i for i, e in enumerate(order) if e in friendly), default=-1
    )

    assert last_friendly < first_money, "a money emoji is reached before a friendly one"


async def test_a_pack_without_a_trolley_gets_a_cheerful_duck_instead() -> None:
    """The real UtyaDuck case, pinned."""
    bot = Bot(emoji=["🤑", "🤩", "💰", "👋"])

    assert await StickerBook("Pack").for_section(bot, "shop") == "file-🤩"


async def test_the_wallet_may_still_use_money() -> None:
    """The one screen where money is the subject, not the motive."""
    bot = Bot(emoji=["💰", "🤩"])

    assert await StickerBook("Pack").for_section(bot, "wallet") == "file-💰"


def test_the_default_pack_is_the_full_one() -> None:
    """The larger set covers more emoji, so more screens get a sticker that is
    about them rather than a shared fallback.

    Pinned because the default is what every install without an explicit
    setting gets, and it is a one-word change with a visible effect.
    """
    from geekvpn.infrastructure.config.settings import TelegramSettings

    assert TelegramSettings().sticker_set == "UtyaDuckFull"


def _sections_sent() -> set[str]:
    """Every section name passed to a sticker send, read from the source.

    `ast` rather than a regex: the section is the last argument of calls whose
    other arguments are themselves calls (`kwargs.get("bot")`), and a regex
    that stops at the first bracket reads the wrong one.
    """
    import ast

    found: set[str] = set()
    handlers = pathlib.Path("src/geekvpn/presentation/bot/handlers")
    for source in handlers.glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            name = (
                target.attr
                if isinstance(target, ast.Attribute)
                else target.id
                if isinstance(target, ast.Name)
                else ""
            )
            if name not in {"send", "_decorate"}:
                continue
            last = node.args[-1] if node.args else None
            if isinstance(last, ast.Constant) and isinstance(last.value, str):
                found.add(last.value)
    return found


def test_every_section_defined_is_a_section_somebody_sends():
    """A sticker nothing sends is a sticker nobody sees.

    `delivered` sat in this map with no sender at all: the entry was written,
    the emoji were chosen, and the one moment in the bot worth celebrating
    passed in silence. `settings` had the opposite shape - a screen a customer
    can open with no entry here, so it opened bare.

    Both are the same mistake, and it is invisible by construction: stickers
    fail quietly on purpose, so neither a missing sender nor a missing entry
    can ever surface as an error at runtime.
    """
    missing = sorted(set(SECTION_EMOJI) - _sections_sent())

    assert not missing, f"defined but never sent: {missing}"


def test_every_sticker_sent_has_emoji_to_look_for():
    """The other direction: a section sent with no entry here resolves to
    nothing, and the screen opens bare."""
    unknown = sorted(_sections_sent() - set(SECTION_EMOJI))

    assert not unknown, f"sent with no emoji defined: {unknown}"
