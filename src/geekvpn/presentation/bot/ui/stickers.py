"""One sticker per section, taken from a real pack at runtime.

A sticker is addressed by `file_id`, and a `file_id` cannot be written down
here: it is issued by Telegram and there is no way to know a valid one without
asking. So nothing is hard-coded. The bot reads a named pack once, on first
use, and matches each section to the sticker whose own emoji fits it.

That has three properties worth the indirection:

* the pack is a setting, so an operator can swap it for their own without a
  deploy;
* a pack missing an emoji simply yields no sticker for that section, and the
  section still works - a bot that refuses to open a screen because a duck is
  missing is worse than a screen with no duck;
* nothing in this file can go stale, because there are no ids in it.

Stickers are sent when a section is *opened from the keyboard*, never on
inline navigation. Telegram cannot edit a sticker into an existing message, so
one per callback would leave a column of ducks behind a customer trying to
read a price.
"""

from __future__ import annotations

from typing import Any, Final

import structlog

logger = structlog.stdlib.get_logger(__name__)

#: Which sticker belongs to which screen, by the emoji the pack assigns it.
#:
#: Several candidates each, in order: packs disagree about which emoji they
#: cover, and the second choice is better than nothing. Chosen to read as the
#: section's own subject - money for the wallet, a question for support.
SECTION_EMOJI: Final[dict[str, tuple[str, ...]]] = {
    "welcome": ("👋", "🥰", "😊"),
    "shop": ("🛒", "🤑", "💸"),
    "dashboard": ("😎", "👍", "🤩"),
    "wallet": ("💰", "🤑", "💵"),
    "referral": ("🎁", "🤝", "🥳"),
    "support": ("🤔", "😢", "🙏"),
    "faq": ("🤓", "🤔", "📚"),
    "status": ("👀", "😐", "🤨"),
    "profile": ("😇", "😊", "👤"),
    "delivered": ("🎉", "🥳", "🤩"),
}


class StickerBook:
    """Resolves a section to a sticker, once, then remembers.

    Held per process rather than per request: a pack is tens of stickers and
    does not change while the bot is running, so fetching it on every screen
    would be a Telegram round trip in front of a customer for decoration.
    """

    def __init__(self, set_name: str) -> None:
        self._set_name = set_name.strip()
        self._by_emoji: dict[str, str] | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._set_name)

    async def for_section(self, bot: Any, section: str) -> str | None:
        if not self.enabled or bot is None:
            return None

        book = await self._load(bot)
        for emoji in SECTION_EMOJI.get(section, ()):
            found = book.get(emoji)
            if found:
                return found
        return None

    async def _load(self, bot: Any) -> dict[str, str]:
        if self._by_emoji is not None:
            return self._by_emoji

        try:
            pack = await bot.get_sticker_set(self._set_name)
        except Exception:
            # A wrong name, a deleted pack, a network blip. Logged once and
            # then treated as "no stickers" forever, rather than retried in
            # front of every customer who opens a screen.
            logger.info("stickers.unavailable", set_name=self._set_name)
            self._by_emoji = {}
            return self._by_emoji

        found: dict[str, str] = {}
        for sticker in getattr(pack, "stickers", ()):
            emoji = getattr(sticker, "emoji", None)
            # First wins: packs repeat emoji, and the earlier one is usually
            # the plainer drawing.
            if emoji and emoji not in found:
                found[emoji] = sticker.file_id
        self._by_emoji = found
        # Logged on success too, not only on failure. Silence used to mean
        # either "the pack loaded" or "this never ran", and telling those apart
        # cost a round trip to the server and back.
        logger.info(
            "stickers.loaded",
            set_name=self._set_name,
            emoji=len(found),
            covered=sorted(
                section
                for section, candidates in SECTION_EMOJI.items()
                if any(candidate in found for candidate in candidates)
            ),
        )
        return found


async def send(bot: Any, chat_id: int, book: StickerBook | None, section: str) -> None:
    """Best effort, always. A missing sticker must never cost a screen."""
    if book is None:
        return
    try:
        file_id = await book.for_section(bot, section)
        if file_id:
            await bot.send_sticker(chat_id, file_id)
    except Exception:
        logger.info("stickers.send_failed", section=section)


__all__ = ["SECTION_EMOJI", "StickerBook", "send"]
