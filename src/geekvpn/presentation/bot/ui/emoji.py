"""Named emoji constants.

Centralised so the visual language stays consistent and a redesign is one
file, not a grep across forty handlers.
"""

from __future__ import annotations

from typing import Final

# Navigation
HOME: Final = "\U0001f3e0"
BACK: Final = "\U0001f519"
NEXT: Final = "\u25c0\ufe0f"
PREV: Final = "\u25b6\ufe0f"
CLOSE: Final = "\u2716\ufe0f"
REFRESH: Final = "\U0001f504"

# Sections
SHOP: Final = "\U0001f6d2"
DASHBOARD: Final = "\U0001f4ca"
WALLET: Final = "\U0001f45b"
REFERRAL: Final = "\U0001f381"
SUPPORT: Final = "\U0001f4ac"
PROFILE: Final = "\U0001f464"
SETTINGS: Final = "\u2699\ufe0f"
FAQ: Final = "\u2753"
STATUS: Final = "\U0001f4e1"
NOTIFICATIONS: Final = "\U0001f514"
RENEW: Final = "\U0001f501"

# Product tiers
DIRECT: Final = "\U0001f680"
TURBO: Final = "\u26a1"
ELITE: Final = "\U0001f451"
TRIAL: Final = "\U0001f381"

# State
OK: Final = "\u2705"
FAIL: Final = "\u274c"
WARN: Final = "\u26a0\ufe0f"
INFO: Final = "\u2139\ufe0f"
PENDING: Final = "\u23f3"
ACTIVE: Final = "\U0001f7e2"
EXPIRING: Final = "\U0001f7e1"
EXPIRED: Final = "\U0001f534"
DEGRADED: Final = "\U0001f7e0"

# Commerce
FIRE: Final = "\U0001f525"
DISCOUNT: Final = "\U0001f3f7\ufe0f"
COUPON: Final = "\U0001f39f\ufe0f"
CASHBACK: Final = "\U0001f4b0"
CARD: Final = "\U0001f4b3"
CRYPTO: Final = "\u20bf"
RECEIPT: Final = "\U0001f9fe"
CART: Final = "\U0001f6cd\ufe0f"

# Misc
KEY: Final = "\U0001f511"
LINK: Final = "\U0001f517"
QR: Final = "\U0001f4f1"
CLOCK: Final = "\u23f0"
CALENDAR: Final = "\U0001f4c5"
CHART: Final = "\U0001f4c8"
SPARKLE: Final = "\u2728"
MEDAL: Final = "\U0001f3c5"
CROWN: Final = "\U0001f451"
ROCKET: Final = "\U0001f680"
GLOBE: Final = "\U0001f30d"
SHIELD: Final = "\U0001f6e1\ufe0f"
DEVICE: Final = "\U0001f4bb"
DOC: Final = "\U0001f4c4"
SEND: Final = "\U0001f4e4"

TIER_EMOJI: Final = {
    "bronze": "\U0001f949",
    "silver": "\U0001f948",
    "gold": "\U0001f947",
    "diamond": "\U0001f48e",
}
