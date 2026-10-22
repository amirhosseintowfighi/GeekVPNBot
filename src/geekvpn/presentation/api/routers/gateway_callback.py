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

import base64
import hashlib
import html
import json
import uuid
from typing import Final

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse

from geekvpn.application.ports.cache import Cache
from geekvpn.domain.payments.enums import VerificationOutcome
from geekvpn.infrastructure.di.container import Container
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.infrastructure.payments.gateway_verification import verify_payment

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


#: Styled like the Mini App: the same near-black surface, card, hairline border
#: and blue-to-purple accent, so the customer ends where they started rather
#: than on a page that looks like an error. Kept self-contained - no web font
#: or external file - because this page is reached from a bank's redirect, often
#: with the customer's VPN off, where a blocked CDN would mean no design at all.
_STYLE = """
:root{--bg:#0a0a0f;--card:#111118;--border:#24242e;--fg:#fafafa;--muted:#9d9daa;
--primary:#6c5ce7;--accent:#9b59e6;--tone:#6c5ce7;--radius:1rem}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{font-family:Vazirmatn,"Vazir",Tahoma,system-ui,-apple-system,"Segoe UI",sans-serif;
background:var(--bg);color:var(--fg);direction:rtl;-webkit-font-smoothing:antialiased;
display:grid;place-items:center;min-height:100vh;padding:24px;
background-image:radial-gradient(60% 50% at 50% 0%,rgba(108,92,231,.22) 0%,transparent 100%)}
.card{position:relative;width:100%;max-width:24rem;text-align:center;background:var(--card);
border:1px solid var(--border);border-radius:calc(var(--radius) * 1.25);padding:36px 24px 28px;
box-shadow:0 20px 60px rgba(0,0,0,.45)}
.card::before{content:"";position:absolute;inset:-1px;border-radius:inherit;padding:1px;
background:linear-gradient(135deg,rgba(77,124,232,.9),rgba(155,89,230,.35));
-webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);
-webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none}
.badge{width:76px;height:76px;margin:0 auto;border-radius:50%;display:grid;place-items:center;
color:var(--tone);background:color-mix(in srgb,var(--tone) 14%,transparent);
box-shadow:0 0 0 8px color-mix(in srgb,var(--tone) 7%,transparent),
0 0 40px color-mix(in srgb,var(--tone) 35%,transparent)}
.badge svg{width:38px;height:38px}
.ok{--tone:#2bb673}.pending{--tone:#f5a524}.failed{--tone:#e5484d}.unknown{--tone:#f5a524}
h1{font-size:21px;font-weight:800;margin:22px 0 10px;letter-spacing:-.2px}
p{color:var(--muted);margin:0;line-height:2;font-size:15px}
.btn{display:block;margin-top:26px;padding:14px 20px;border-radius:var(--radius);
background:linear-gradient(135deg,var(--primary),var(--accent));color:#fff;font-weight:700;
text-decoration:none;box-shadow:0 8px 24px rgba(108,92,231,.35)}
.hint{margin-top:20px;font-size:13px;color:var(--muted);opacity:.8}
.brand{margin-top:22px;font-size:12px;letter-spacing:.5px;color:var(--muted);opacity:.6;direction:ltr}
"""

#: One icon per outcome, drawn inline: an emoji renders differently on every
#: phone, and an image would need another request and another CSP source.
_ICONS: Final[dict[str, str]] = {
    "ok": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "failed": '<path d="M7 7l10 10M17 7L7 17"/>',
    "pending": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "unknown": '<path d="M12 7.5v6"/><path d="M12 16.8v.2"/><circle cx="12" cy="12" r="9"/>',
}

_PAGE = """<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="dark">
<meta name="theme-color" content="#0a0a0f">
<title>{title}</title>
<style>{style}</style></head>
<body><main class="card {tone}">
<div class="badge"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{icon}</svg></div>
<h1>{title}</h1><p>{body}</p>{action}
<div class="hint">می‌تونی این صفحه رو ببندی.</div>
<div class="brand">GeekVPN</div>
</main></body></html>"""

_APP_BUTTON = '<a class="btn" href="{href}">بازگشت به اپ</a><script>{script}</script>'


def _csp_hash(content: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


#: Computed once: the stylesheet never changes between responses.
_STYLE_HASH: Final = _csp_hash(_STYLE)


def _policy(script: str | None) -> str:
    """This page's own CSP, replacing the API's `default-src 'none'`.

    That global policy is right for JSON and is why this page used to render
    as bare black-on-white text: it blocked the inline stylesheet, and the
    script that returns an Android customer to the app. Each is allowed here
    by its exact hash, so nothing else inline can run - no `unsafe-inline`.
    """
    script_src = _csp_hash(script) if script is not None else "'none'"
    return (
        "default-src 'none'; "
        f"style-src {_STYLE_HASH}; "
        f"script-src {script_src}; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    )


def _page(
    tone: str, title: str, body: str, *, status_code: int = 200, app_link: str | None = None
) -> HTMLResponse:
    action = ""
    script: str | None = None
    if app_link is not None:
        # Chrome may block the automatic hop into another app; the button is
        # the way back that always works.
        script = f"location.replace({json.dumps(app_link)});"
        action = _APP_BUTTON.format(href=html.escape(app_link, quote=True), script=script)
    page = _PAGE.format(
        style=_STYLE,
        tone=tone,
        icon=_ICONS[tone],
        title=title,
        body=body,
        action=action,
    )
    return HTMLResponse(
        page,
        status_code=status_code,
        # The middleware only sets a policy when the route has not: this wins.
        headers={"Content-Security-Policy": _policy(script)},
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

    try:
        # In the payment's own shop: a reseller's payment must be asked about
        # with the reseller's merchant account, not ours.
        outcome = str((await run_in_threadpool(verify_payment, container, payment_id)).outcome)
    except Exception:
        logger.exception("gateway.callback_failed", payment_id=payment_id)
        return _page(
            "unknown",
            "نتیجهٔ پرداخت مشخص نشد",
            "اگه مبلغ از حسابت کم شده، نگران نباش — به پشتیبانی پیام بده و همون‌جا پیگیری می‌کنیم.",
            status_code=502,
            app_link=app_link("unknown"),
        )

    if outcome == str(VerificationOutcome.CONFIRMED):
        return _page(
            "ok",
            "پرداختت تأیید شد",
            "حسابت همین الان شارژ شد و سفارشت فعال شد."
            f"<br>برگرد به {back} و VPN رو دوباره روشن کن.",
            app_link=app_link("ok"),
        )
    if outcome == str(VerificationOutcome.INCONCLUSIVE):
        # Not a failure. The provider was unreachable, and the sweeper will ask
        # again - telling the customer it failed would have them pay twice.
        return _page(
            "pending",
            "در حال بررسی پرداخت",
            f"چند لحظهٔ دیگه نتیجه رو تو {back} بهت می‌گیم.",
            app_link=app_link("pending"),
        )
    return _page(
        "failed",
        "پرداخت انجام نشد",
        "چیزی از حسابت کم نشده. می‌تونی دوباره امتحان کنی.",
        app_link=app_link("failed"),
    )


@router.post("/callback/{payment_id}", response_model=None)
async def gateway_notification(
    payment_id: str, request: Request, background: BackgroundTasks
) -> HTMLResponse | JSONResponse:
    """A provider saying "this one settled" - AtlasPay's per-order webhook -
    or a customer's browser sent back by a POST form.

    The browser gets the same page a GET would: some bank pages return the
    customer with a form post, and a raw JSON reply at the end of paying
    reads as "something broke".

    Treated as a knock, never as news: the body is not read, so a forged
    one achieves exactly what a forged GET does - we ask the provider, on our
    own connection, and it says no. That is also why no signature secret is
    needed to trust it.

    Answered before the asking happens. AtlasPay waits five seconds and never
    retries, while verifying can mean a panel call to deliver the service; a
    late answer would only cost the speed-up, but there is no reason to.
    """
    if "text/html" in request.headers.get("accept", ""):
        return await gateway_callback(payment_id, request)
    container = request.app.state.container
    background.add_task(_verify_quietly, container, payment_id)
    return JSONResponse({"ok": True})


async def _verify_quietly(container: Container, payment_id: str) -> None:
    try:
        await run_in_threadpool(verify_payment, container, payment_id)
    except Exception:
        # The worker's sweep asks again within half a minute.
        logger.warning("gateway.notification_verify_failed", payment_id=payment_id, exc_info=True)
