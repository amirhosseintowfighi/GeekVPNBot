"""Request scope.

One database session, one set of repositories, one audit recorder, one set of
use cases - built once per request or per Telegram update and thrown away
afterwards.

Why a scope object rather than fifteen FastAPI dependencies: the wiring lives
in one readable place, the bot and the API share it verbatim, and a use case
can never accidentally be constructed with two different sessions (which is
how "why did half my transaction commit?" bugs happen).

Everything is a `cached_property`, so an endpoint that only needs the settings
service does not pay for constructing an Argon2-backed admin login use case.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from functools import cached_property

from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.application.catalog.catalog_admin import CatalogAdminService
from geekvpn.application.catalog.duration_ladder import DurationLadderService
from geekvpn.application.catalog.policy_provider import PricingPolicyProvider
from geekvpn.application.catalog.promotion_admin import PromotionAdminService
from geekvpn.application.catalog.quoting_service import QuotingService
from geekvpn.application.catalog.storefront_service import StorefrontService
from geekvpn.application.identity.authenticate_admin import AuthenticateAdmin
from geekvpn.application.identity.authenticate_telegram import AuthenticateTelegramUser
from geekvpn.application.identity.authorization import AuthorizationService
from geekvpn.application.identity.manage_admins import ManageAdmins
from geekvpn.application.identity.session_service import SessionService
from geekvpn.application.platform.settings_service import SettingsService
from geekvpn.application.provisioning.order_service import OrderService
from geekvpn.application.provisioning.provisioning_service import ProvisioningService
from geekvpn.application.provisioning.usage_sync import UsageSyncService
from geekvpn.domain.identity.enums import SubjectType
from geekvpn.domain.identity.errors import AccountSuspendedError
from geekvpn.infrastructure.audit.recorder import AuditLogRecorder
from geekvpn.infrastructure.di.container import Container
from geekvpn.infrastructure.di.sync_scope import LoggingEventPublisher, Uuid4IdGenerator
from geekvpn.infrastructure.panels.provider import DatabasePanelProvider
from geekvpn.infrastructure.persistence.repositories.admin import SqlAlchemyAdminRepository
from geekvpn.infrastructure.persistence.repositories.audit import SqlAlchemyAuditLogRepository
from geekvpn.infrastructure.persistence.repositories.catalog import (
    SqlAlchemyCampaignRepository,
    SqlAlchemyCategoryRepository,
    SqlAlchemyCouponRepository,
    SqlAlchemyPlanRepository,
    SqlAlchemyProductRepository,
)
from geekvpn.infrastructure.persistence.repositories.nodes import (
    SqlAlchemyNodeRepository,
)
from geekvpn.infrastructure.persistence.repositories.provisioning import (
    JalaliOrderNumbers,
    SqlAlchemyOrderRepository,
    SqlAlchemySubscriptionRepository,
)
from geekvpn.infrastructure.persistence.repositories.session import (
    SqlAlchemySessionRepository,
)
from geekvpn.infrastructure.persistence.repositories.settings import DbSettingsStore
from geekvpn.infrastructure.persistence.repositories.user import SqlAlchemyUserRepository
from geekvpn.infrastructure.security.ip_allowlist import IpAllowlist


# Deliberately not `slots=True`: `cached_property` needs a real instance
# `__dict__`, and the object is short-lived enough that the memory saving would
# be meaningless anyway.
@dataclass
class RequestScope:
    """Everything bound to a single database session."""

    container: Container
    session: AsyncSession

    # -- repositories ------------------------------------------------------

    @cached_property
    def users(self) -> SqlAlchemyUserRepository:
        return SqlAlchemyUserRepository(self.session)

    @cached_property
    def admins(self) -> SqlAlchemyAdminRepository:
        return SqlAlchemyAdminRepository(self.session)

    @cached_property
    def session_repository(self) -> SqlAlchemySessionRepository:
        return SqlAlchemySessionRepository(self.session)

    @cached_property
    def audit_repository(self) -> SqlAlchemyAuditLogRepository:
        return SqlAlchemyAuditLogRepository(self.session)

    @cached_property
    def settings_store(self) -> DbSettingsStore:
        return DbSettingsStore(self.session, redis=self.container.redis)

    @cached_property
    def catalog_categories(self) -> SqlAlchemyCategoryRepository:
        return SqlAlchemyCategoryRepository(self.session)

    @cached_property
    def catalog_products(self) -> SqlAlchemyProductRepository:
        return SqlAlchemyProductRepository(self.session)

    @cached_property
    def catalog_plans(self) -> SqlAlchemyPlanRepository:
        return SqlAlchemyPlanRepository(self.session)

    @cached_property
    def catalog_coupons(self) -> SqlAlchemyCouponRepository:
        return SqlAlchemyCouponRepository(self.session)

    @cached_property
    def catalog_campaigns(self) -> SqlAlchemyCampaignRepository:
        return SqlAlchemyCampaignRepository(self.session)

    # -- services ----------------------------------------------------------

    @cached_property
    def audit(self) -> AuditLogRecorder:
        return AuditLogRecorder(repository=self.audit_repository, clock=self.container.clock)

    @cached_property
    def sessions(self) -> SessionService:
        return SessionService(
            sessions=self.session_repository,
            access_tokens=self.container.access_tokens,
            refresh_tokens=self.container.refresh_tokens,
            clock=self.container.clock,
            audit=self.audit,
            revocations=self.container.revocations,
            user_policy=self.container.user_session_policy,
            admin_policy=self.container.admin_session_policy,
            access_ttl_seconds=int(self.container.settings.auth.access_ttl.total_seconds()),
        )

    @cached_property
    def authorization(self) -> AuthorizationService:
        return AuthorizationService(audit=self.audit)

    @cached_property
    def settings_service(self) -> SettingsService:
        return SettingsService(store=self.settings_store, audit=self.audit)

    @cached_property
    def pricing_policies(self) -> PricingPolicyProvider:
        """Reads the pricing knobs from runtime settings.

        Cached per request, so a storefront render that prices sixty packages
        reads the policy once rather than sixty times.
        """
        return PricingPolicyProvider(self.settings_store)

    @cached_property
    def storefront(self) -> StorefrontService:
        return StorefrontService(
            categories=self.catalog_categories,
            products=self.catalog_products,
            plans=self.catalog_plans,
            campaigns=self.catalog_campaigns,
            policies=self.pricing_policies,
            clock=self.container.clock,
        )

    @cached_property
    def quoting(self) -> QuotingService:
        return QuotingService(
            plans=self.catalog_plans,
            products=self.catalog_products,
            campaigns=self.catalog_campaigns,
            coupons=self.catalog_coupons,
            policies=self.pricing_policies,
            clock=self.container.clock,
        )

    @cached_property
    def duration_ladder(self) -> DurationLadderService:
        """Bulk plan generation.

        It existed as a finished service with tests and no caller for the whole
        of phase 12 - nothing outside its own test file ever constructed it, so
        the ladder could not be generated from anywhere a person could reach.
        """
        return DurationLadderService(self.catalog_admin)

    @cached_property
    def catalog_admin(self) -> CatalogAdminService:
        return CatalogAdminService(
            categories=self.catalog_categories,
            products=self.catalog_products,
            plans=self.catalog_plans,
            clock=self.container.clock,
            audit=self.audit,
        )

    @cached_property
    def promotions(self) -> PromotionAdminService:
        return PromotionAdminService(
            coupons=self.catalog_coupons,
            campaigns=self.catalog_campaigns,
            clock=self.container.clock,
            audit=self.audit,
        )

    # -- use cases ---------------------------------------------------------

    @cached_property
    def authenticate_telegram(self) -> AuthenticateTelegramUser:
        verifier = self.container.telegram_auth
        if verifier is None:
            raise RuntimeError(
                "Telegram authentication is unavailable: TELEGRAM__BOT_TOKEN is not set."
            )
        return AuthenticateTelegramUser(
            users=self.users,
            verifier=verifier,
            sessions=self.sessions,
            clock=self.container.clock,
            audit=self.audit,
            request_max_age_seconds=(
                self.container.settings.telegram.mini_app_request_max_age_seconds
            ),
        )

    @cached_property
    def authenticate_admin(self) -> AuthenticateAdmin:
        return AuthenticateAdmin(
            admins=self.admins,
            passwords=self.container.passwords,
            totp=self.container.totp,
            sessions=self.sessions,
            clock=self.container.clock,
            audit=self.audit,
            rate_limiter=self.container.rate_limiter,
            allowlist=IpAllowlist.from_entries(self.container.settings.auth.admin_ip_allowlist),
        )

    @cached_property
    def manage_admins(self) -> ManageAdmins:
        return ManageAdmins(
            admins=self.admins,
            sessions=self.session_repository,
            passwords=self.container.passwords,
            clock=self.container.clock,
            audit=self.audit,
        )

    # -- orders and provisioning -------------------------------------------

    @cached_property
    def orders(self) -> SqlAlchemyOrderRepository:
        return SqlAlchemyOrderRepository(self.session)

    @cached_property
    def subscriptions(self) -> SqlAlchemySubscriptionRepository:
        return SqlAlchemySubscriptionRepository(self.session)

    @cached_property
    def nodes(self) -> SqlAlchemyNodeRepository:
        return SqlAlchemyNodeRepository(self.session)

    @cached_property
    def panel_provider(self) -> DatabasePanelProvider:
        """Builds panel adapters from stored node credentials.

        Request-scoped, so its adapter cache - and therefore its connection
        pools - cannot outlive the credentials it was built from. Callers that
        finish with it should ``await scope.panel_provider.aclose()``; the API
        and bot scope teardown does this.
        """
        return DatabasePanelProvider(nodes=self.nodes)

    @cached_property
    def order_service(self) -> OrderService:
        return OrderService(
            orders=self.orders,
            clock=self.container.clock,
            ids=Uuid4IdGenerator(),
            numbers=JalaliOrderNumbers(self.session),
            events=LoggingEventPublisher(),
        )

    @cached_property
    def provisioning(self) -> ProvisioningService:
        return ProvisioningService(
            orders=self.orders,
            subscriptions=self.subscriptions,
            nodes=self.nodes,
            panels=self.panel_provider,
            clock=self.container.clock,
            ids=Uuid4IdGenerator(),
            events=LoggingEventPublisher(),
        )

    @cached_property
    def usage_sync(self) -> UsageSyncService:
        """Reads traffic figures back from the panels.

        Shared by the operator's "sync now" button and the scheduled sweep, so
        the two can never disagree about what a reading means.
        """
        return UsageSyncService(
            subscriptions=self.subscriptions,
            nodes=self.nodes,
            panels=self.panel_provider,
            clock=self.container.clock,
        )

    # -- helpers -----------------------------------------------------------

    async def aclose(self) -> None:
        """Release anything the scope opened beyond the database session.

        Only the panel provider holds sockets, and only if something in this
        request actually built an adapter - hence the ``__dict__`` check rather
        than touching the property and constructing one just to close it.
        """
        provider = self.__dict__.get("panel_provider")
        if provider is not None:
            await provider.aclose()

    async def resolve_role(
        self, subject_type: SubjectType, subject_id: uuid.UUID
    ) -> tuple[str | None, tuple[str, ...]]:
        """Role resolver used during refresh.

        Re-reading the admin on every refresh is what makes a permission change
        take effect within one access-token lifetime instead of at next login.
        A disabled account also stops refreshing here.
        """
        if subject_type is not SubjectType.ADMIN:
            return None, ()
        admin = await self.admins.get(subject_id)
        if admin is None or not admin.status.can_authenticate:
            raise AccountSuspendedError()
        return admin.role.value, tuple(sorted(p.value for p in admin.permissions))


def build_scope(container: Container, session: AsyncSession) -> RequestScope:
    return RequestScope(container=container, session=session)
