"""Cache key construction and expiry policy. No Redis, so it is testable.

The two failure modes this file is shaped around
-----------------------------------------------
**Serving one customer's data to another.** Every mistake of this kind is the
same mistake: a key that does not contain everything the value depends on. An
analytics answer depends on the day range *and* on the operator's permissions; a
wallet balance depends on the user. So keys are built from an explicit set of
parts and a key with no identifying part is refused outright rather than quietly
shared.

**The stampede.** A popular key expiring at a fixed moment sends every in-flight
request to the database at once, and the more traffic there is the worse it gets.
Two defences: the TTL is jittered so a thousand keys written in the same second
do not expire in the same second, and ``lock_key`` gives the caller a single
flight lock so only the first miss recomputes.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Mapping
from typing import Any, Final

NAMESPACE: Final = "geekvpn"
SEPARATOR: Final = ":"

#: Ten per cent either side. Enough to spread a stampede over a few seconds,
#: small enough that a five-minute report is never twenty minutes stale.
JITTER_RATIO: Final = 0.1

#: How long a single-flight lock is held. Must exceed the slowest computation it
#: guards or a second worker starts while the first is still running; must stay
#: short enough that a crashed worker does not block recomputation for long.
LOCK_TTL_SECONDS: Final = 30

#: Serving a slightly stale answer while one worker refreshes is better than a
#: thundering herd, so values may be kept past their logical freshness.
STALE_GRACE_SECONDS: Final = 60


class CacheKeyError(ValueError):
    """The key would not have identified the value it caches."""


def _normalise(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        # str(True) is "True" and str(1) is "1"; without this, True and 1 would
        # share a cache entry.
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set, frozenset)):
        # Sorted, so that permissions in a different order are the same key
        # rather than two entries for the same answer.
        return ",".join(sorted(_normalise(item) for item in value))
    text = str(value)
    # Colons would create key segments that are not there, which is how one key
    # can be made to collide with another by choosing a clever username.
    return text.replace(SEPARATOR, "|")


def _fingerprint(parts: Mapping[str, Any]) -> str:
    """Stable digest of the parts, sorted by name.

    Digested rather than spelled out because a key holding a date range, a set of
    permissions and a segment filter would be several hundred bytes, and Redis
    stores the key as well as the value.
    """
    material = SEPARATOR.join(f"{name}={_normalise(parts[name])}" for name in sorted(parts))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def build_key(prefix: str, **parts: Any) -> str:
    """``geekvpn:<prefix>:<fingerprint of every part>``."""
    if not prefix:
        raise CacheKeyError("A cache key needs a prefix.")
    if not parts:
        # A parameterless key is almost always a bug in the making: the first
        # time a filter is added to the query, the old shared entry is served.
        raise CacheKeyError(
            f"Cache key {prefix!r} has no parts; a key that identifies nothing is shared by everyone."
        )
    return f"{NAMESPACE}{SEPARATOR}{prefix}{SEPARATOR}{_fingerprint(parts)}"


def scoped_key(prefix: str, *, subject_id: Any, **parts: Any) -> str:
    """A key for data belonging to one person.

    The subject is a mandatory keyword rather than one part among many, because
    forgetting it is the single most expensive cache bug available: one customer
    sees another customer's wallet.
    """
    # ``.strip()`` matters: a whitespace-only subject is an empty subject that
    # happens to be non-empty as a string, and it would build a perfectly valid
    # looking key that identifies nobody. Found by a test that expected the
    # refusal and did not get it.
    if subject_id is None or _normalise(subject_id).strip() in ("", "-"):
        raise CacheKeyError("A per-subject cache key requires a subject id.")
    return build_key(prefix, subject=subject_id, **parts)


def lock_key(key: str) -> str:
    """The single-flight lock guarding recomputation of ``key``."""
    return f"{key}{SEPARATOR}lock"


def jittered_ttl(
    ttl_seconds: int,
    *,
    ratio: float = JITTER_RATIO,
    rng: random.Random | None = None,
) -> int:
    """Spread expiry so many keys do not fall due in the same second.

    Never returns zero: an integer TTL of zero means "no expiry" to some clients
    and "expire immediately" to others, and neither is what was asked for.
    """
    if ttl_seconds < 1:
        raise CacheKeyError("TTL must be at least one second.")
    source = rng or random
    spread = int(ttl_seconds * ratio)
    if spread < 1:
        return ttl_seconds
    return max(1, ttl_seconds + source.randint(-spread, spread))


def invalidation_pattern(prefix: str) -> str:
    """Glob for every key under a prefix, for use with ``SCAN``.

    Deliberately paired with SCAN and never with ``KEYS``: ``KEYS`` blocks the
    whole Redis instance while it walks the keyspace, which on a production
    dataset is an outage caused by a cache invalidation.
    """
    if not prefix:
        raise CacheKeyError("An invalidation pattern needs a prefix.")
    return f"{NAMESPACE}{SEPARATOR}{prefix}{SEPARATOR}*"


#: Freshness by kind of data, in seconds. Money is short, reference data is long.
#: Written as a table so the choices can be argued with in one place instead of
#: being scattered as literals across services.
TTLS: Final[dict[str, int]] = {
    "analytics.bundle": 300,
    "analytics.dashboard": 120,
    "analytics.export": 900,
    "catalog.storefront": 600,
    "catalog.plan": 600,
    "settings.platform": 300,
    # Never cached longer than a few seconds: a customer who has just topped up
    # and sees an old balance opens a support ticket immediately.
    "wallet.balance": 10,
    "support.queue": 30,
    "notify.unread": 15,
}


def ttl_for(kind: str) -> int:
    if kind not in TTLS:
        raise CacheKeyError(f"No TTL defined for {kind!r}; add it to TTLS deliberately.")
    return TTLS[kind]


def should_cache(kind: str) -> bool:
    """Whether this kind of data may be cached at all.

    Some answers must never be cached and the honest place to say so is here.
    Anything to do with authorisation is in this category: a cached permission
    check keeps working after access is revoked.
    """
    return not kind.startswith(("auth.", "permissions.", "session."))


__all__ = [
    "JITTER_RATIO",
    "LOCK_TTL_SECONDS",
    "NAMESPACE",
    "STALE_GRACE_SECONDS",
    "TTLS",
    "CacheKeyError",
    "build_key",
    "invalidation_pattern",
    "jittered_ttl",
    "lock_key",
    "scoped_key",
    "should_cache",
    "ttl_for",
]
