"""Which payment the next receipt photo belongs to.

A card payment started in the Mini App ends outside it: the customer taps a
button, the app closes, and the receipt arrives in the bot chat as a photo with
no conversation behind it. The bot can guess when exactly one payment is
waiting for proof, and cannot when two are - which is the case this exists for.

So the Mini App says which one *before* the app closes, and the bot reads it
when the photo arrives. Two processes, one short-lived fact, so it lives in the
cache rather than in either of their memories.

The key is here rather than at either end because a shared key written twice is
a key that disagrees with itself, silently, the first time one side is edited.
"""

from __future__ import annotations

from typing import Final

#: Long enough to switch apps, find the receipt and send it; short enough that
#: an abandoned intent cannot capture a photo sent about something else an hour
#: later. It is only ever a hint: the bot re-checks that the payment is still
#: awaiting proof and still belongs to the sender.
RECEIPT_INTENT_TTL_SECONDS: Final = 1_800

#: Template for the message the bot sends when the Mini App asks it to.
RECEIPT_REQUESTED_TEMPLATE: Final = "payment.receipt_requested"


def receipt_intent_key(telegram_id: int) -> str:
    return f"receipt-intent:{telegram_id}"


__all__ = [
    "RECEIPT_INTENT_TTL_SECONDS",
    "RECEIPT_REQUESTED_TEMPLATE",
    "receipt_intent_key",
]
