"""CSRF double-submit protection, and its honest scope."""

from __future__ import annotations

import pytest

from geekvpn.infrastructure.security.csrf import (
    CsrfError,
    check_request,
    cookie_settings,
    issue_token,
    refresh_cookie_settings,
    verify_token,
)

SECRET = "a-signing-secret-of-entirely-sufficient-length"
SESSION = "3f0c9a2e-0000-4000-8000-000000000001"


class TestTokens:
    def test_a_freshly_issued_token_verifies(self):
        assert verify_token(SECRET, issue_token(SECRET, session_id=SESSION), session_id=SESSION)

    def test_tokens_are_unique_per_issue(self):
        tokens = {issue_token(SECRET, session_id=SESSION) for _ in range(50)}
        assert len(tokens) == 50

    def test_a_token_from_another_session_is_refused(self):
        """Otherwise one leaked token works against every operator."""
        token = issue_token(SECRET, session_id=SESSION)
        assert not verify_token(SECRET, token, session_id="another-session")

    def test_a_token_signed_with_another_secret_is_refused(self):
        token = issue_token("a-completely-different-secret-of-good-length", session_id=SESSION)
        assert not verify_token(SECRET, token, session_id=SESSION)

    def test_a_tampered_signature_is_refused(self):
        token = issue_token(SECRET, session_id=SESSION)
        nonce, _, signature = token.partition(".")
        flipped = "B" if signature[0] != "B" else "C"
        assert not verify_token(SECRET, f"{nonce}.{flipped}{signature[1:]}", session_id=SESSION)

    def test_garbage_is_refused_without_raising(self):
        for value in (None, "", "no-separator", ".", "a.", ".b"):
            assert not verify_token(SECRET, value, session_id=SESSION)

    def test_a_short_secret_is_refused_at_issue_time(self):
        """A forgeable signature is not protection."""
        with pytest.raises(CsrfError):
            issue_token("tooshort", session_id=SESSION)


class TestRequestChecking:
    def _token(self):
        return issue_token(SECRET, session_id=SESSION)

    def test_a_valid_double_submit_passes(self):
        token = self._token()
        verdict = check_request(
            SECRET,
            method="POST",
            cookie_token=token,
            header_token=token,
            session_id=SESSION,
        )
        assert verdict.ok

    def test_a_missing_header_fails(self):
        """The forged cross-site POST: the cookie rides along, the header cannot."""
        verdict = check_request(
            SECRET,
            method="POST",
            cookie_token=self._token(),
            header_token=None,
            session_id=SESSION,
        )
        assert not verdict.ok
        assert verdict.reason == "missing token"

    def test_mismatched_halves_fail(self):
        verdict = check_request(
            SECRET,
            method="POST",
            cookie_token=self._token(),
            header_token=self._token(),
            session_id=SESSION,
        )
        assert not verdict.ok
        assert verdict.reason == "token mismatch"

    def test_matching_but_unsigned_halves_fail(self):
        """Matching alone is not enough: a cookie-writing attacker sets both."""
        verdict = check_request(
            SECRET,
            method="POST",
            cookie_token="forged.value",
            header_token="forged.value",
            session_id=SESSION,
        )
        assert not verdict.ok
        assert verdict.reason == "bad signature"

    def test_a_token_valid_for_another_session_fails(self):
        token = issue_token(SECRET, session_id="someone-else")
        verdict = check_request(
            SECRET,
            method="POST",
            cookie_token=token,
            header_token=token,
            session_id=SESSION,
        )
        assert not verdict.ok

    def test_safe_methods_need_no_token(self):
        for method in ("GET", "HEAD", "OPTIONS"):
            assert check_request(
                SECRET,
                method=method,
                cookie_token=None,
                header_token=None,
                session_id=SESSION,
            ).ok

    def test_options_is_exempt_so_preflight_does_not_break(self):
        assert check_request(
            SECRET, method="OPTIONS", cookie_token=None, header_token=None, session_id=SESSION
        ).ok

    def test_bearer_authenticated_requests_are_exempt(self):
        """A cross-site page cannot set an Authorization header.

        Demanding a token here would be ceremony that breaks API clients while
        protecting nothing.
        """
        verdict = check_request(
            SECRET,
            method="POST",
            cookie_token=None,
            header_token=None,
            session_id=SESSION,
            has_bearer_token=True,
        )
        assert verdict.ok
        assert verdict.reason == "bearer authenticated"

    def test_the_method_check_is_case_insensitive(self):
        assert check_request(
            SECRET, method="get", cookie_token=None, header_token=None, session_id=SESSION
        ).ok


class TestCookieAttributes:
    def test_the_refresh_cookie_is_not_readable_by_javascript(self):
        assert refresh_cookie_settings(deployed=True, max_age_seconds=60)["httponly"] is True

    def test_the_csrf_cookie_must_be_readable_by_javascript(self):
        """The browser has to echo it into a header; that is the whole mechanism."""
        assert cookie_settings(deployed=True)["httponly"] is False

    def test_cookies_are_secure_when_deployed(self):
        assert cookie_settings(deployed=True)["secure"] is True
        assert refresh_cookie_settings(deployed=True, max_age_seconds=60)["secure"] is True

    def test_cookies_are_not_secure_locally(self):
        """Otherwise local development over http silently drops them."""
        assert cookie_settings(deployed=False)["secure"] is False

    def test_samesite_is_set_on_both(self):
        assert cookie_settings(deployed=True)["samesite"] == "lax"
        assert refresh_cookie_settings(deployed=True, max_age_seconds=60)["samesite"] == "lax"

    def test_the_refresh_cookie_is_scoped_to_the_auth_path(self):
        """It has no business being attached to every request in the app."""
        assert refresh_cookie_settings(deployed=True, max_age_seconds=60)["path"].endswith("/auth")
