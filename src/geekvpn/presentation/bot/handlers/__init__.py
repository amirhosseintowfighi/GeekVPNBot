"""Bot handlers.

Each module owns one flow and exposes a module-level `router`. `factory.py`
is the only place that knows the registration order.

The modules are imported here so that `from geekvpn.presentation.bot.handlers
import shop` works from anywhere - `fallback.py` in particular imports its
siblings to hand reply-keyboard taps over to the inline flows.
"""

from geekvpn.presentation.bot.handlers import (
    admin_export,
    admin_texts,
    admin_top,
    app_login,
    channel_leave,
    common,
    dashboard,
    fallback,
    faq,
    menu,
    profile,
    purchase,
    referral,
    renewal,
    rules,
    server_status,
    service_owner,
    settings,
    shop,
    start,
    support,
    system,
    trial,
    wallet,
)

__all__ = [
    "admin_export",
    "admin_texts",
    "admin_top",
    "app_login",
    "channel_leave",
    "common",
    "dashboard",
    "fallback",
    "faq",
    "menu",
    "profile",
    "purchase",
    "referral",
    "renewal",
    "rules",
    "server_status",
    "service_owner",
    "settings",
    "shop",
    "start",
    "support",
    "system",
    "trial",
    "wallet",
]
