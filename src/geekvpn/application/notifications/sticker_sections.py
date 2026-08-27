"""Which sticker belongs to which moment, by the emoji a pack assigns it.

Data only, and here rather than in the bot because two processes need it. The
bot decorates a screen someone just opened; the API and worker processes
decorate a notification they are pushing - an approved receipt, a delivered
service - and those never run inside the bot.

No `file_id` appears anywhere: a `file_id` is issued by Telegram and cannot be
written down in advance. Each side reads a named pack once and matches these
emoji against it, so a renamed or deleted pack costs a decoration and nothing
more.

Ordered candidates, not one choice. Packs disagree about which emoji they
cover: UtyaDuck carries thirty-six and had none of `👀 😐 🤨` for the server
status or `😇 😊 👤` for the profile, so those screens opened bare while the
others were decorated. The tail of each list is therefore a deliberate
second-best - an emoji another section already proved this pack has. A sticker
shared between two screens is worth more than one screen with nothing, and the
first entries still win wherever a pack does cover them.
"""

from __future__ import annotations

from typing import Final

SECTION_EMOJI: Final[dict[str, tuple[str, ...]]] = {
    "welcome": ("👋", "🥰", "😊"),
    # Money emoji last, and only as a last resort.
    #
    # UtyaDuck has no 🛒, so the shop fell through to 🤑 - a duck with dollar
    # signs for eyes, on the screen where a customer decides whether to trust
    # us with their money. It reads as "we want your money" where it needs to
    # read as "you are about to get something good", and the difference is
    # worth an emoji.
    "shop": ("🛒", "🤩", "😍", "😎", "👍", "💸", "🤑"),
    "dashboard": ("😎", "👍", "🤩"),
    # The one screen where money is the subject rather than the motive.
    "wallet": ("💰", "🤑", "💵"),
    "referral": ("🎁", "🤝", "🥳"),
    "support": ("🤔", "😢", "🙏"),
    "faq": ("🤓", "🤔", "📚"),
    "status": ("👀", "😐", "🤨", "😎", "👍", "🤩"),
    "profile": ("😇", "😊", "👤", "👋", "🥰"),
    "settings": ("🧐", "🤔", "😎", "👍"),
    # The one screen in the customer's bot that is an offer rather than a
    # service. A handshake if the pack has one, money if it does not - this is
    # the single place where a money emoji is the honest subject.
    "reseller": ("🤝", "🤑", "💰", "😎"),
    # The rest are moments rather than screens.
    #
    # A customer who has just photographed a bank transfer is at the least
    # certain point of the whole flow, and an acknowledgement they can see at a
    # glance is worth more there than on any menu.
    "receipt": ("📨", "🤝", "👍", "😎"),
    "approved": ("🤑", "🥳", "🎉", "👍"),
    "delivered": ("🎉", "🥳", "🤩"),
}

#: Notifications worth decorating, by template key.
#:
#: Only the two that mean something arrived. An expiry warning or a rejected
#: payment gets no duck: a sticker on bad news reads as mockery, and a sticker
#: on everything is a sticker on nothing.
NOTIFICATION_STICKERS: Final[dict[str, str]] = {
    "payment.approved": "approved",
    "purchase.delivered": "delivered",
    "purchase.delivered_no_link": "delivered",
}

__all__ = ["NOTIFICATION_STICKERS", "SECTION_EMOJI"]
