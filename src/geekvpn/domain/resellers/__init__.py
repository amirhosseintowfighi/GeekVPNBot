"""Resellers: people who sell this service under their own name.

A reseller is not a customer with a discount. Three things separate them, and
each one is a reason this is its own aggregate rather than a flag on a user:

* **They buy at their own prices.** A percentage off the list price, with
  per-package overrides where a percentage is the wrong shape.
* **They spend credit, not money.** A reseller tops up once and draws down as
  they provision, so every sale is a balance check rather than a payment flow.
* **They are confined to the panels they were given.** An operator who sells
  Germany must not be able to provision on the node reserved for somebody
  else's contract.

They also run their own Telegram bot, but that lives outside this package:
the token is infrastructure, and which bot a customer arrived through is a
routing question, not a pricing one.
"""

from geekvpn.domain.resellers.enums import ResellerStatus
from geekvpn.domain.resellers.errors import (
    InsufficientCredit,
    NodeNotAllowed,
    ResellerNotFound,
    ResellerSuspended,
)
from geekvpn.domain.resellers.reseller import PriceOverride, Reseller

__all__ = [
    "InsufficientCredit",
    "NodeNotAllowed",
    "PriceOverride",
    "Reseller",
    "ResellerNotFound",
    "ResellerStatus",
    "ResellerSuspended",
]
