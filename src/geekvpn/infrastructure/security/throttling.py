"""Rate-limiting policy: what is limited, how hard, and under what key.

Deliberately free of Redis and FastAPI imports. The decisions in this file are
the part that is easy to get wrong and the part worth testing, so they live
where a test can reach them without a server. ``sliding_window.py`` holds the
Redis mechanics; this holds the judgement.

The three mistakes this file exists to avoid
-------------------------------------------
1. **One global limit.** A limit loose enough for browsing the shop is useless
   on the login endpoint, and a limit tight enough for login makes the Mini App
   unusable. Limits are per purpose.
2. **Keying on IP alone.** Iranian mobile carriers put tens of thousands of
   subscribers behind one NAT address, so an IP-keyed login limit is a denial of
   service against a whole carrier. Authenticated traffic keys on the subject;
   only anonymous traffic falls back to IP.
3. **Counting a failed login the same as a successful one.** The thing worth
   limiting is *failure*. A customer who logs in correctly forty times has done
   nothing wrong.
"""

from __future__ import annotations

import enum
import hashlib
from dataclasses import dataclass
from typing import Final

DEFAULT_LIMIT: Final = 120
DEFAULT_WINDOW_SECONDS: Final = 60

#: After this many consecutive failures the account is locked, not merely
#: throttled. Throttling slows an attacker down; it does not stop a slow,
#: patient one.
LOCKOUT_THRESHOLD: Final = 8
LOCKOUT_BASE_SECONDS: Final = 60
LOCKOUT_MAX_SECONDS: Final = 3600

#: A captcha is demanded before the lockout threshold, so a human who forgot
#: their password gets a puzzle rather than a locked account.
CAPTCHA_THRESHOLD: Final = 3


class Scope(enum.StrEnum):
    """What the limit is counted against."""

    IP = "ip"
    SUBJECT = "subject"
    #: Both, whichever is stricter. Used where an authenticated attacker with
    #: many accounts behind one address is the threat.
    SUBJECT_AND_IP = "subject_and_ip"


@dataclass(frozen=True, slots=True)
class Policy:
    name: str
    limit: int
    window_seconds: int
    scope: Scope = Scope.SUBJECT_AND_IP
    #: When true, only failed attempts are counted.
    failures_only: bool = False
    #: A single request may cost more than one unit. A report export is one
    #: request and a great deal of database work.
    cost: int = 1

    def __post_init__(self) -> None:
        if self.limit < 1 or self.window_seconds < 1 or self.cost < 1:
            raise ValueError("A policy needs a positive limit, window and cost.")


#: The policy table. Every limited operation names its policy explicitly rather
#: than matching a URL pattern: a route rename must not silently remove a limit.
POLICIES: Final[dict[str, Policy]] = {
    # --- authentication -----------------------------------------------------
    "auth.login": Policy(
        "auth.login", limit=5, window_seconds=300, scope=Scope.SUBJECT_AND_IP, failures_only=True
    ),
    "auth.admin_login": Policy(
        "auth.admin_login", limit=5, window_seconds=900, scope=Scope.IP, failures_only=True
    ),
    "auth.totp": Policy(
        "auth.totp", limit=6, window_seconds=300, scope=Scope.SUBJECT, failures_only=True
    ),
    "auth.recovery_code": Policy(
        "auth.recovery_code", limit=5, window_seconds=900, scope=Scope.SUBJECT, failures_only=True
    ),
    "auth.refresh": Policy("auth.refresh", limit=60, window_seconds=3600, scope=Scope.SUBJECT),
    "auth.telegram": Policy("auth.telegram", limit=20, window_seconds=300, scope=Scope.IP),
    "auth.captcha": Policy("auth.captcha", limit=20, window_seconds=600, scope=Scope.IP),
    # --- money --------------------------------------------------------------
    # Tight on purpose. Each of these creates a row a human then has to review,
    # so the limit protects the operator's queue as much as the server.
    "payments.checkout": Policy("payments.checkout", limit=10, window_seconds=600),
    "payments.receipt": Policy("payments.receipt", limit=15, window_seconds=600),
    "payments.topup": Policy("payments.topup", limit=10, window_seconds=600),
    "wallet.read": Policy("wallet.read", limit=120, window_seconds=60),
    # --- support ------------------------------------------------------------
    "support.open_ticket": Policy("support.open_ticket", limit=5, window_seconds=3600),
    "support.reply": Policy("support.reply", limit=30, window_seconds=600),
    "support.search": Policy("support.search", limit=30, window_seconds=60),
    # --- read paths ---------------------------------------------------------
    "catalog.browse": Policy("catalog.browse", limit=240, window_seconds=60, scope=Scope.IP),
    "miniapp.read": Policy("miniapp.read", limit=180, window_seconds=60),
    # --- expensive admin work ----------------------------------------------
    "analytics.dashboard": Policy("analytics.dashboard", limit=60, window_seconds=60, cost=2),
    "analytics.export": Policy("analytics.export", limit=6, window_seconds=600, cost=10),
    "admin.broadcast": Policy("admin.broadcast", limit=5, window_seconds=3600),
    "admin.mutation": Policy("admin.mutation", limit=120, window_seconds=60),
}


class UnknownPolicyError(KeyError):
    """A limited operation named a policy that does not exist.

    Raised at call time rather than defaulted, because a typo silently falling
    back to a loose default is how a money endpoint ends up unlimited.
    """


def policy_for(name: str) -> Policy:
    try:
        return POLICIES[name]
    except KeyError as exc:
        raise UnknownPolicyError(f"No rate limit policy named {name!r}.") from exc


def _hash_identifier(value: str) -> str:
    """Short, stable digest of an identifier.

    Redis keys end up in slow logs and in ``KEYS`` output during incidents. A
    Telegram id or an IP address in a key is personal data sitting in an
    operational tool, so the key holds a digest instead. Twelve hex characters is
    plenty: a collision merely shares a counter, and the namespace is per policy.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def keys_for(
    policy: Policy,
    *,
    subject_id: str | None = None,
    ip: str | None = None,
) -> tuple[str, ...]:
    """Every counter key this policy must check.

    Returns more than one key for ``SUBJECT_AND_IP``: the request is allowed only
    if every counter allows it.
    """
    keys: list[str] = []
    wants_subject = policy.scope in (Scope.SUBJECT, Scope.SUBJECT_AND_IP)
    wants_ip = policy.scope in (Scope.IP, Scope.SUBJECT_AND_IP)

    if wants_subject and subject_id:
        keys.append(f"{policy.name}:s:{_hash_identifier(subject_id)}")
    if wants_ip and ip:
        keys.append(f"{policy.name}:i:{_hash_identifier(ip)}")

    if not keys:
        # An anonymous request to a subject-scoped policy with no client address
        # is unattributable. One shared bucket is the safe reading: it cannot be
        # used to exhaust anyone else's quota, and it cannot be used to escape a
        # limit either.
        keys.append(f"{policy.name}:anon")
    return tuple(keys)


def lockout_seconds(consecutive_failures: int) -> int:
    """Exponential back-off, capped.

    Uncapped doubling reaches years, which turns a forgotten password into a
    permanently destroyed account and a support ticket we cannot close. One hour
    is long enough that online guessing is hopeless.
    """
    if consecutive_failures < LOCKOUT_THRESHOLD:
        return 0
    excess = consecutive_failures - LOCKOUT_THRESHOLD
    return min(LOCKOUT_BASE_SECONDS * (2**excess), LOCKOUT_MAX_SECONDS)


def requires_captcha(consecutive_failures: int) -> bool:
    return consecutive_failures >= CAPTCHA_THRESHOLD


@dataclass(frozen=True, slots=True)
class Decision:
    """The outcome of checking every counter for one request."""

    allowed: bool
    policy_name: str
    limit: int
    remaining: int
    retry_after_seconds: int

    def headers(self) -> dict[str, str]:
        """``X-RateLimit-*`` plus ``Retry-After``.

        Sent on allowed responses too, so a well-behaved client can slow itself
        down instead of discovering the limit by being refused.
        """
        values = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(self.remaining, 0)),
            "X-RateLimit-Policy": self.policy_name,
        }
        if not self.allowed:
            values["Retry-After"] = str(max(self.retry_after_seconds, 1))
        return values


def combine(policy: Policy, verdicts: tuple[tuple[bool, int, int], ...]) -> Decision:
    """Fold per-key verdicts into one decision: the strictest key wins.

    Each verdict is ``(allowed, remaining, retry_after_seconds)``.
    """
    if not verdicts:
        raise ValueError("At least one verdict is required.")
    allowed = all(item[0] for item in verdicts)
    remaining = min(item[1] for item in verdicts)
    retry_after = max(item[2] for item in verdicts) if not allowed else 0
    return Decision(
        allowed=allowed,
        policy_name=policy.name,
        limit=policy.limit,
        remaining=remaining,
        retry_after_seconds=retry_after,
    )


RETRY_MESSAGE_FA: Final = "تعداد درخواست‌های شما زیاد بوده است. لطفاً {seconds} ثانیه دیگر تلاش کنید."
LOCKED_MESSAGE_FA: Final = (
    "به دلیل تلاش‌های ناموفق، حساب شما موقتاً قفل شده است. {seconds} ثانیه دیگر تلاش کنید."
)


__all__ = [
    "CAPTCHA_THRESHOLD",
    "DEFAULT_LIMIT",
    "DEFAULT_WINDOW_SECONDS",
    "LOCKED_MESSAGE_FA",
    "LOCKOUT_MAX_SECONDS",
    "LOCKOUT_THRESHOLD",
    "POLICIES",
    "RETRY_MESSAGE_FA",
    "Decision",
    "Policy",
    "Scope",
    "UnknownPolicyError",
    "combine",
    "keys_for",
    "lockout_seconds",
    "policy_for",
    "requires_captcha",
]
