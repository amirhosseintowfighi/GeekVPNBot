"""The catch-all for anything a handler raises.

Telegram retries any update the webhook does not answer with a 2xx, forever and
with no backoff worth the name. So a single handler bug does not stay a bug: it
becomes a redelivery loop that repeats the same failure several times a second
against every worker at once.

Two things stop that, and both are needed. This router turns an unhandled
exception into a Persian apology and a log line. The webhook in ``app.py``
additionally acks whatever happens, because a router cannot catch a failure in
the dispatcher itself.

Registered first, not last: aiogram matches error handlers separately from
message handlers, so position carries no filter meaning here, and putting it at
the top keeps it visible next to the thing it protects.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery, ErrorEvent, Message

from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.presentation.bot.ui import text as T

logger = get_logger("bot.errors")

router = Router(name="errors")


@router.errors()
async def on_error(event: ErrorEvent) -> bool:
    """Log, apologise, and swallow.

    Returns ``True`` so aiogram treats the update as handled. Returning
    ``False`` would re-raise into the webhook and produce the 500 this exists
    to prevent.
    """
    update = event.update
    logger.exception(
        "bot.handler_failed",
        update_id=getattr(update, "update_id", None),
        error=str(event.exception),
    )

    # Best-effort only. The customer already saw a failure; a second one while
    # apologising must not escalate into the redelivery loop we are avoiding.
    try:
        callback: CallbackQuery | None = getattr(update, "callback_query", None)
        if callback is not None:
            await callback.answer(T.ERR_GENERIC, show_alert=True)
            return True

        message: Message | None = getattr(update, "message", None)
        if message is not None:
            await message.answer(T.ERR_GENERIC)
    except Exception:  # noqa: S110 - see below
        # Telegram refuses to answer an expired callback, and an apology that
        # fails must not become the error it is apologising for.
        pass

    return True
