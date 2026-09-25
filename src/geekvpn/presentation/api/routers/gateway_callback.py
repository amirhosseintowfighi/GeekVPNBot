"""Where a customer lands after paying at an online gateway.

Unauthenticated, and it has to be: the customer arrives in a browser redirected
by the provider, carrying no session and no token. What protects it is that it
proves nothing and grants nothing - it names a payment, and every decision
about that payment is made by asking the provider directly.

So a stranger hitting this endpoint with a guessed id achieves exactly one
thing: the platform asks ZarinPal whether that payment succeeded, and ZarinPal
says no. There is no state to corrupt, because `VerificationService.verify`
takes the provider's word and nothing from this request.

The customer sees a page, not JSON. They came from a bank, and a browser
showing a raw object is the last thing anybody wants at the end of paying.
"""

from __future__ import annotations

import html
import json
import uuid
from typing import Final

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from geekvpn.application.ports.cache import Cache
from geekvpn.domain.payments.enums import VerificationOutcome
from geekvpn.infrastructure.di.sync_scope import SyncScope
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.presentation.api.admin_common import mutate_scope

logger = get_logger(__name__)

router = APIRouter(prefix="/pay", tags=["payments"], include_in_schema=False)

#: The Android app's way back in. Its bank page returns here like everyone
#: else's; a payment the app started is remembered, so this page can offer the
#: link into the app instead of telling the customer to go back to the bot.
APP_RESULT_URI: Final = "geekvpn://payment/result"
#: Longer than any gateway keeps a customer on its page.
APP_RETURN_TTL_SECONDS: Final = 86_400


def _app_return_key(stored_id: str) -> str:
    return f"pay:app_return:{stored_id}"


async def remember_app_payment(cache: Cache, payment_id: uuid.UUID) -> None:
    """Mark a gateway payment as started from the Android app."""
    await cache.set(_app_return_key(payment_id.hex), "1", ttl_seconds=APP_RETURN_TTL_SECONDS)


async def _started_in_app(cache: Cache, payment_id: str) -> bool:
    try:
        stored_id = uuid.UUID(payment_id).hex
    except ValueError:
        return False
    return await cache.get(_app_return_key(stored_id)) is not None


_PAGE = """<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  body{{font-family:system-ui,sans-serif;background:#0b0f14;color:#e6edf3;
       display:grid;place-items:center;min-height:100vh;margin:0;padding:24px}}
  .card{{max-width:26rem;text-align:center;background:#141a22;border-radius:16px;
        padding:32px 24px;box-shadow:0 10px 40px rgba(0,0,0,.4)}}
  .mark{{font-size:56px;line-height:1}}
  h1{{font-size:20px;margin:16px 0 8px}}
  p{{color:#9fb0c0;margin:0;line-height:1.9}}
  .btn{{display:inline-block;margin-top:24px;padding:12px 28px;border-radius:12px;
        background:#00acfe;color:#031b33;font-weight:700;text-decoration:none}}
</style></head>
<body><div class="card"><div class="mark">{mark}</div>
<h1>{title}</h1><p>{body}</p>{action}</div></body></html>"""

_APP_BUTTON = (
    '<a class="btn" href="{href}">\u0628\u0627\u0632\u06af\u0634\u062a \u0628\u0647 \u0627\u067e</a>'
    "<script>location.replace({href_js});</script>"
)


def _page(
    mark: str, title: str, body: str, *, status_code: int = 200, app_link: str | None = None
) -> HTMLResponse:
    action = ""
    if app_link is not None:
        # Chrome may block the automatic hop into another app; the button is
        # the way back that always works.
        action = _APP_BUTTON.format(
            href=html.escape(app_link, quote=True),
            href_js=json.dumps(app_link),
        )
    return HTMLResponse(
        _PAGE.format(mark=mark, title=title, body=body, action=action), status_code=status_code
    )


@router.get("/callback/{payment_id}", response_class=HTMLResponse)
async def gateway_callback(payment_id: str, request: Request) -> HTMLResponse:
    """Verify the payment the customer just came back from.

    The provider's query string is deliberately ignored. ZarinPal sends
    `Status=OK`, Zibal sends `success=1`, AqayePardakht sends its own - and all
    three are assertions by a redirect anybody can forge. The only answer worth
    having comes from asking the provider on our own connection, which is what
    `verify` does.
    """
    container = request.app.state.container
    # Asked before verifying, and never allowed to fail the page: the worst a
    # cache outage costs is the customer finding their own way back.
    try:
        from_app = await _started_in_app(container.cache, payment_id)
    except Exception:
        logger.warning("gateway.app_return_unknown", payment_id=payment_id)
        from_app = False
    back = "اپ" if from_app else "ربات"

    def app_link(result: str) -> str | None:
        if not from_app:
            return None
        return f"{APP_RESULT_URI}?payment={html.escape(payment_id)}&result={result}"

    def work(scope: SyncScope) -> str:
        return str(scope.verification.verify(payment_id).outcome)

    try:
        outcome = await mutate_scope(container, work)
    except Exception:
        logger.exception("gateway.callback_failed", payment_id=payment_id)
        return _page(
            "⚠️",
            "نتیجهٔ پرداخت مشخص نشد",
            "اگه مبلغ از حسابت کم شده، نگران نباش — به پشتیبانی پیام بده "
            "و همون‌جا پیگیری می‌کنیم.",
            status_code=502,
            app_link=app_link("unknown"),
        )

    if outcome == str(VerificationOutcome.CONFIRMED):
        return _page(
            "✅",
            "پرداختت تأیید شد",
            f"برگرد به {back} — سرویست همون‌جا آماده‌ست.",
            app_link=app_link("ok"),
        )
    if outcome == str(VerificationOutcome.INCONCLUSIVE):
        # Not a failure. The provider was unreachable, and the sweeper will ask
        # again - telling the customer it failed would have them pay twice.
        return _page(
            "⏳",
            "در حال بررسی پرداخت",
            f"چند لحظهٔ دیگه نتیجه رو تو {back} بهت می‌گیم.",
            app_link=app_link("pending"),
        )
    return _page(
        "❌",
        "پرداخت انجام نشد",
        "چیزی از حسابت کم نشده. می‌تونی دوباره امتحان کنی.",
        app_link=app_link("failed"),
    )
