"""The page a customer lands on after paying must actually render its design.

The API's global policy is `default-src 'none'`, which blocks inline `<style>`
and `<script>`. The callback page relied on both, so customers saw bare black
text on white, and the Android app's automatic return never fired. The page
now sends its own policy that allows exactly its own style and script, by
hash, and nothing else.
"""

from __future__ import annotations

import base64
import hashlib
import re

from geekvpn.presentation.api.routers.gateway_callback import _page


def _hash(content: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode() + "'"


def _policy(response) -> dict[str, str]:
    header = response.headers["content-security-policy"]
    return {
        part.strip().split(" ", 1)[0]: part.strip().split(" ", 1)[1] if " " in part.strip() else ""
        for part in header.split(";")
        if part.strip()
    }


def _inline(tag: str, html: str) -> list[str]:
    return re.findall(rf"<{tag}>(.*?)</{tag}>", html, re.DOTALL)


def test_the_page_allows_its_own_stylesheet_by_hash() -> None:
    response = _page("ok", "پرداختت تأیید شد", "برگرد به ربات.")
    html = response.body.decode()

    styles = _inline("style", html)
    assert styles, "the page has no stylesheet"
    assert _hash(styles[0]) in _policy(response)["style-src"]


def test_the_app_return_script_is_allowed_by_hash() -> None:
    response = _page("ok", "پرداختت تأیید شد", "برگرد به اپ.", app_link="geekvpn://payment/result")
    html = response.body.decode()

    scripts = _inline("script", html)
    assert scripts, "the app return has no script"
    assert _hash(scripts[0]) in _policy(response)["script-src"]


def test_nothing_else_inline_is_allowed() -> None:
    policy = _policy(_page("ok", "t", "b"))

    assert "'unsafe-inline'" not in " ".join(policy.values())
    assert policy["default-src"] == "'none'"
    assert policy["frame-ancestors"] == "'none'"
