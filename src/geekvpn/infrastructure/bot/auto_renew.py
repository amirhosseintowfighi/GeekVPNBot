"""The worker's auto-renew pass (see ``application.provisioning.auto_renew``).

A renewal is the same wallet checkout the app and the bot use, with
``renews_subscription_id`` set, so pricing, coupons, the ledger, provisioning
and the customer's "service renewed" message all stay in one place.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from geekvpn.application.provisioning.auto_renew import (
    AutoRenewResult,
    RenewalCandidate,
    is_due,
)
from geekvpn.domain.base.errors import DomainError
from geekvpn.domain.payments.errors import InsufficientFunds
from geekvpn.domain.provisioning.errors import DeliveryPending
from geekvpn.infrastructure.bot.services import build_bot_services
from geekvpn.infrastructure.di.container import Container
from geekvpn.infrastructure.di.scope import build_scope
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.infrastructure.persistence.repositories.auto_renew import SqlAutoRenewals

logger = get_logger(__name__)


@dataclass(slots=True)
class AutoRenewReport:
    results: dict[str, int] = field(default_factory=dict)

    def add(self, result: AutoRenewResult) -> None:
        self.results[result.value] = self.results.get(result.value, 0) + 1


async def run_auto_renewals(container: Container) -> AutoRenewReport:
    report = AutoRenewReport()
    now = container.clock.now()
    async with container.session_factory() as session:
        due = [c for c in await SqlAutoRenewals(session).candidates(now) if is_due(c, now)]
    for candidate in due:
        # One transaction per renewal: a customer without balance must not
        # hold back the next one.
        result = await _renew(container, candidate)
        report.add(result)
        async with container.session_factory() as session:
            await SqlAutoRenewals(session).record(
                candidate.subscription_id, result, container.clock.now()
            )
            await session.commit()
    return report


async def _renew(container: Container, candidate: RenewalCandidate) -> AutoRenewResult:
    async with container.session_factory() as session:
        scope = build_scope(container, session)
        try:
            user = await scope.users.get_by_telegram_id(candidate.telegram_id)
            if user is None or candidate.plan_id is None:
                return AutoRenewResult.UNAVAILABLE
            services = build_bot_services(scope)
            await services.checkout.pay_from_wallet(
                user.id,
                plan_id=uuid.UUID(candidate.plan_id),
                renews_subscription_id=candidate.subscription_id,
            )
            await session.commit()
            logger.info("auto_renew.renewed", subscription_id=candidate.subscription_id)
            return AutoRenewResult.RENEWED
        except DeliveryPending:
            # Paid; the provisioning retry queue finishes it.
            return AutoRenewResult.PENDING
        except InsufficientFunds:
            await session.rollback()
            return AutoRenewResult.INSUFFICIENT_FUNDS
        except DomainError as exc:
            await session.rollback()
            logger.info(
                "auto_renew.refused",
                subscription_id=candidate.subscription_id,
                error=type(exc).__name__,
            )
            return AutoRenewResult.UNAVAILABLE
        except Exception:
            await session.rollback()
            logger.exception("auto_renew.failed", subscription_id=candidate.subscription_id)
            return AutoRenewResult.UNAVAILABLE
        finally:
            await scope.aclose()


__all__ = ["AutoRenewReport", "run_auto_renewals"]
