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

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from geekvpn.domain.payments.enums import VerificationOutcome
from geekvpn.infrastructure.di.sync_scope import SyncScope
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.presentation.api.admin_common import mutate_scope

logger = get_logger(__name__)

router = APIRouter(prefix="/pay", tags=["payments"], include_in_schema=False)

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
</style></head>
<body><div class="card"><div class="mark">{mark}</div>
<h1>{title}</h1><p>{body}</p></div></body></html>"""


def _page(mark: str, title: str, body: str, *, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        _PAGE.format(mark=mark, title=title, body=body), status_code=status_code
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

    def work(scope: SyncScope) -> str:
        return str(scope.verification.verify(payment_id).outcome)

    try:
        outcome = await mutate_scope(container, work)
    except Exception:
        logger.exception("gateway.callback_failed", payment_id=payment_id)
        return _page(
            "⚠️",
            "نتیجه‌ی پرداخت مشخص نشد",
            "اگر مبلغ از حسابتان کم شده، نگران نباشید — به پشتیبانی پیام بدهید "
            "و همان‌جا پیگیری می‌کنیم.",
            status_code=502,
        )

    if outcome == str(VerificationOutcome.CONFIRMED):
        return _page(
            "✅",
            "پرداخت شما تأیید شد",
            "به ربات برگردید — سرویس‌تان همان‌جا آماده است.",
        )
    if outcome == str(VerificationOutcome.INCONCLUSIVE):
        # Not a failure. The provider was unreachable, and the sweeper will ask
        # again - telling the customer it failed would have them pay twice.
        return _page(
            "⏳",
            "در حال بررسی پرداخت",
            "چند لحظه دیگر نتیجه را در ربات به شما اطلاع می‌دهیم.",
        )
    return _page(
        "❌",
        "پرداخت انجام نشد",
        "مبلغی از حساب شما کم نشده است. می‌توانید دوباره تلاش کنید.",
    )
