"""Cache key construction and expiry policy."""

from __future__ import annotations

import random

import pytest

from geekvpn.infrastructure.cache.keys import (
    JITTER_RATIO,
    NAMESPACE,
    TTLS,
    CacheKeyError,
    build_key,
    invalidation_pattern,
    jittered_ttl,
    lock_key,
    scoped_key,
    should_cache,
    ttl_for,
)


class TestKeyIdentity:
    def test_keys_are_namespaced(self):
        """A shared Redis instance must not have our keys loose at the root."""
        assert build_key("analytics.bundle", days=30).startswith(f"{NAMESPACE}:")

    def test_different_parameters_give_different_keys(self):
        """Otherwise a 7-day report is served for a 30-day request."""
        assert build_key("analytics.bundle", days=7) != build_key("analytics.bundle", days=30)

    def test_the_same_parameters_give_the_same_key(self):
        assert build_key("analytics.bundle", days=30) == build_key("analytics.bundle", days=30)

    def test_parameter_order_does_not_matter(self):
        """Two entries for one answer halves the hit rate for no reason."""
        assert build_key("x", a=1, b=2) == build_key("x", b=2, a=1)

    def test_different_prefixes_never_collide(self):
        assert build_key("revenue", days=30) != build_key("retention", days=30)

    def test_true_and_one_are_not_the_same_key(self):
        """str(True) is "True" but a sloppy normaliser turns both into "1"."""
        assert build_key("x", flag=True) != build_key("x", flag=1)

    def test_none_and_the_empty_string_are_distinguished(self):
        assert build_key("x", v=None) != build_key("x", v="")

    def test_a_colon_in_a_value_cannot_forge_a_key_segment(self):
        """A crafted username must not be able to collide with another key."""
        assert build_key("x", user="a:b") != build_key("x", user="a", b="")

    def test_permission_sets_in_a_different_order_share_one_entry(self):
        """Same permissions, same answer; the order they arrive in is noise."""
        assert build_key("x", perms=["b", "a"]) == build_key("x", perms=["a", "b"])

    def test_a_key_with_no_parameters_is_refused(self):
        """A key identifying nothing is shared by everyone the day a filter is added."""
        with pytest.raises(CacheKeyError):
            build_key("analytics.bundle")

    def test_an_empty_prefix_is_refused(self):
        with pytest.raises(CacheKeyError):
            build_key("", days=30)


class TestPerSubjectKeys:
    def test_two_customers_never_share_an_entry(self):
        """The most expensive cache bug available: one wallet shown to another."""
        assert scoped_key("wallet.balance", subject_id=1001) != scoped_key(
            "wallet.balance", subject_id=1002
        )

    def test_a_missing_subject_is_refused_loudly(self):
        for bad in (None, "", "   "):
            with pytest.raises(CacheKeyError):
                scoped_key("wallet.balance", subject_id=bad)

    def test_a_scoped_key_still_varies_with_its_other_parameters(self):
        assert scoped_key("statement", subject_id=1001, page=1) != scoped_key(
            "statement", subject_id=1001, page=2
        )


class TestExpiry:
    def test_jitter_stays_within_the_declared_band(self):
        rng = random.Random(1)
        for _ in range(200):
            value = jittered_ttl(300, rng=rng)
            assert 300 * (1 - JITTER_RATIO) - 1 <= value <= 300 * (1 + JITTER_RATIO) + 1

    def test_jitter_actually_spreads_expiry(self):
        """A thousand keys written in one second must not expire in one second."""
        rng = random.Random(2)
        assert len({jittered_ttl(300, rng=rng) for _ in range(100)}) > 10

    def test_a_tiny_ttl_is_never_reduced_to_zero(self):
        """Zero means "never expire" to some clients and "expire now" to others."""
        rng = random.Random(3)
        for _ in range(50):
            assert jittered_ttl(1, rng=rng) >= 1
            assert jittered_ttl(5, rng=rng) >= 1

    def test_a_zero_ttl_is_a_programming_error(self):
        with pytest.raises(CacheKeyError):
            jittered_ttl(0)

    def test_money_is_cached_far_more_briefly_than_reference_data(self):
        """A customer who just topped up and sees an old balance opens a ticket."""
        assert ttl_for("wallet.balance") < ttl_for("catalog.storefront")
        assert ttl_for("wallet.balance") <= 15

    def test_an_undeclared_kind_raises_instead_of_defaulting(self):
        """An accidental default TTL on money data is a stale-balance bug."""
        with pytest.raises(CacheKeyError):
            ttl_for("wallet.balnace")

    def test_every_declared_ttl_is_positive(self):
        assert all(value > 0 for value in TTLS.values())


class TestSafety:
    def test_authorisation_data_may_not_be_cached(self):
        """A cached permission check keeps working after access is revoked."""
        assert should_cache("auth.session") is False
        assert should_cache("permissions.role") is False
        assert should_cache("session.current") is False

    def test_report_data_may_be_cached(self):
        assert should_cache("analytics.bundle") is True

    def test_the_lock_key_is_distinct_from_the_value_key(self):
        """If they collide, taking the lock destroys the cached value."""
        key = build_key("analytics.bundle", days=30)
        assert lock_key(key) != key
        assert lock_key(key).startswith(key)

    def test_an_invalidation_pattern_is_bounded_to_its_prefix(self):
        """A pattern of "*" would flush every key in a shared Redis."""
        pattern = invalidation_pattern("analytics.bundle")
        assert pattern.startswith(f"{NAMESPACE}:analytics.bundle:")
        assert pattern.endswith("*")
        assert pattern != "*"

    def test_an_empty_invalidation_prefix_is_refused(self):
        with pytest.raises(CacheKeyError):
            invalidation_pattern("")
