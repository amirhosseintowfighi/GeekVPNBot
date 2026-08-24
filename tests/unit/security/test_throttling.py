"""Rate-limiting policy decisions."""

from __future__ import annotations

import pytest

from geekvpn.infrastructure.security.throttling import (
    CAPTCHA_THRESHOLD,
    LOCKOUT_MAX_SECONDS,
    LOCKOUT_THRESHOLD,
    POLICIES,
    Policy,
    UnknownPolicyError,
    combine,
    keys_for,
    lockout_seconds,
    policy_for,
    requires_captcha,
)


class TestPolicyTable:
    def test_every_money_and_auth_path_is_limited(self):
        """The endpoints that cost money or grant access must all be covered."""
        for required in (
            "auth.login",
            "auth.admin_login",
            "auth.totp",
            "auth.recovery_code",
            "payments.checkout",
            "payments.receipt",
            "payments.topup",
            "support.open_ticket",
            # `admin.broadcast` used to be listed here. It was five sends an
            # hour applied to the whole prefix, and a rejected attempt spent the
            # budget too, so an operator debugging a failure locked themselves
            # out of the screen for the rest of the hour. Broadcasts now share
            # `admin.mutation` with the rest of the admin surface. Nothing else
            # in this list moves money or grants access either way - a broadcast
            # does neither.
            "analytics.export",
        ):
            assert required in POLICIES

    def test_an_unknown_policy_raises_instead_of_defaulting(self):
        """A typo must not silently become an unlimited endpoint."""
        with pytest.raises(UnknownPolicyError):
            policy_for("payments.chekout")

    def test_login_is_far_tighter_than_browsing(self):
        login = policy_for("auth.login")
        browse = policy_for("catalog.browse")
        login_rate = login.limit / login.window_seconds
        browse_rate = browse.limit / browse.window_seconds
        assert login_rate < browse_rate / 50

    def test_login_counts_failures_only(self):
        """A customer who signs in correctly all day has done nothing wrong."""
        assert policy_for("auth.login").failures_only is True
        assert policy_for("catalog.browse").failures_only is False

    def test_expensive_reports_cost_more_than_one_unit(self):
        assert policy_for("analytics.export").cost > policy_for("wallet.read").cost

    def test_a_policy_cannot_be_built_with_a_zero_limit(self):
        """limit=0 would refuse everything, which reads as a typo, not a policy."""
        with pytest.raises(ValueError):
            Policy("nonsense", limit=0, window_seconds=60)
        with pytest.raises(ValueError):
            Policy("nonsense", limit=5, window_seconds=0)


class TestKeying:
    def test_subject_and_ip_produce_two_counters(self):
        keys = keys_for(policy_for("payments.checkout"), subject_id="1001", ip="1.2.3.4")
        assert len(keys) == 2

    def test_an_ip_scoped_policy_ignores_the_subject(self):
        """Admin login is IP-scoped: the username is attacker-supplied."""
        keys = keys_for(policy_for("auth.admin_login"), subject_id="1001", ip="1.2.3.4")
        assert len(keys) == 1
        assert ":i:" in keys[0]

    def test_a_subject_scoped_policy_ignores_the_address(self):
        """Carrier NAT means one address is thousands of customers."""
        keys = keys_for(policy_for("auth.totp"), subject_id="1001", ip="1.2.3.4")
        assert len(keys) == 1
        assert ":s:" in keys[0]

    def test_two_customers_behind_one_carrier_address_get_separate_counters(self):
        first = keys_for(policy_for("auth.totp"), subject_id="1001", ip="5.5.5.5")
        second = keys_for(policy_for("auth.totp"), subject_id="1002", ip="5.5.5.5")
        assert first != second

    def test_keys_never_contain_the_raw_identifier(self):
        """Redis keys surface in slow logs; they must not carry personal data."""
        keys = keys_for(policy_for("payments.checkout"), subject_id="1001", ip="85.9.20.144")
        joined = " ".join(keys)
        assert "1001" not in joined
        assert "85.9.20.144" not in joined

    def test_keying_is_stable_across_calls(self):
        """An unstable key resets the counter on every request."""
        args = {"subject_id": "1001", "ip": "1.2.3.4"}
        assert keys_for(policy_for("auth.login"), **args) == keys_for(
            policy_for("auth.login"), **args
        )

    def test_the_same_identifier_does_not_collide_across_policies(self):
        """Sharing a counter between login and checkout would be a lockout bug."""
        login = keys_for(policy_for("auth.login"), subject_id="1001", ip="1.2.3.4")
        checkout = keys_for(policy_for("payments.checkout"), subject_id="1001", ip="1.2.3.4")
        assert set(login).isdisjoint(checkout)

    def test_an_unattributable_request_still_gets_a_counter(self):
        """No subject and no address must not mean no limit."""
        keys = keys_for(policy_for("wallet.read"))
        assert keys == ("wallet.read:anon",)


class TestLockout:
    def test_no_lockout_before_the_threshold(self):
        for failures in range(LOCKOUT_THRESHOLD):
            assert lockout_seconds(failures) == 0

    def test_lockout_grows_but_is_capped(self):
        """Uncapped doubling reaches years and destroys the account."""
        assert lockout_seconds(LOCKOUT_THRESHOLD) > 0
        assert lockout_seconds(LOCKOUT_THRESHOLD + 1) > lockout_seconds(LOCKOUT_THRESHOLD)
        assert lockout_seconds(500) == LOCKOUT_MAX_SECONDS

    def test_a_captcha_is_demanded_before_the_account_is_locked(self):
        """A forgetful human should meet a puzzle, not a locked account."""
        assert CAPTCHA_THRESHOLD < LOCKOUT_THRESHOLD
        assert requires_captcha(CAPTCHA_THRESHOLD) is True
        assert requires_captcha(CAPTCHA_THRESHOLD - 1) is False


class TestCombining:
    def test_the_strictest_counter_wins(self):
        policy = policy_for("payments.checkout")
        decision = combine(policy, ((True, 40, 0), (False, 0, 30)))
        assert decision.allowed is False
        assert decision.retry_after_seconds == 30

    def test_remaining_reports_the_smallest_headroom(self):
        policy = policy_for("payments.checkout")
        decision = combine(policy, ((True, 40, 0), (True, 3, 0)))
        assert decision.allowed is True
        assert decision.remaining == 3

    def test_headers_advertise_the_limit_even_when_allowed(self):
        """A client that can see its headroom does not have to be refused first."""
        decision = combine(policy_for("wallet.read"), ((True, 7, 0),))
        headers = decision.headers()
        assert headers["X-RateLimit-Remaining"] == "7"
        assert "Retry-After" not in headers

    def test_a_refusal_always_carries_a_usable_retry_after(self):
        """Retry-After: 0 tells a client to retry immediately, which is a loop."""
        decision = combine(policy_for("wallet.read"), ((False, 0, 0),))
        assert int(decision.headers()["Retry-After"]) >= 1

    def test_no_verdicts_is_a_programming_error_not_an_allow(self):
        """Folding an empty set must never silently permit the request."""
        with pytest.raises(ValueError):
            combine(policy_for("wallet.read"), ())
