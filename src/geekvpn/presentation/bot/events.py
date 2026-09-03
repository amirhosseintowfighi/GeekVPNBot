"""Getting at the message inside an update.

An outer middleware registered on `dispatcher.update` is handed an `Update`,
not the `Message` or `CallbackQuery` inside it. Two middlewares here were
written as though it were the inner object:

* the anti-flood throttle fell through on every single update, so nothing has
  ever been rate-limited;
* the channel gate matched neither branch, drew nothing, and returned `None` -
  so a customer who had not joined pressed /start and the bot went silent.

Both look like working code. Neither raises, neither logs, and the only symptom
of the first is a bill from Telegram's rate limiter that nobody connects to it.

Hence one helper, used by both, and a test that feeds a real `Update` through a
real `Dispatcher` rather than asserting on what we assume aiogram passes.
"""

from __future__ import annotations

from aiogram.types import CallbackQuery, Message, TelegramObject, Update


def inner_event(event: TelegramObject) -> Message | CallbackQuery | None:
    """The message or callback an update carries, if it carries one.

    Accepts an already-unwrapped object too, so a middleware does not have to
    care which observer it was registered on. `None` for the update kinds no
    middleware here has anything to say about - a poll answer, a chat member
    change - which are passed through untouched.
    """
    if isinstance(event, Message | CallbackQuery):
        return event
    if isinstance(event, Update):
        return event.message or event.callback_query
    return None


__all__ = ["inner_event"]
