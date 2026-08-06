"""SQLAlchemy models.

Importing this package registers every table on `Base.metadata`, which is what
Alembic autogenerate walks. `migrations/env.py` imports it for exactly that
reason - a model that is not imported here is a model that silently never gets
a migration.
"""

from __future__ import annotations

from geekvpn.infrastructure.persistence.models.audit import AuditLogModel
from geekvpn.infrastructure.persistence.models.catalog import (
    CampaignModel,
    CategoryModel,
    CouponModel,
    CouponRedemptionModel,
    PlanModel,
    ProductModel,
)
from geekvpn.infrastructure.persistence.models.identity import (
    AdminModel,
    RefreshTokenModel,
    SessionModel,
    UserModel,
)
from geekvpn.infrastructure.persistence.models.notifications import (
    BroadcastModel,
    NotificationModel,
    NotificationPreferenceModel,
    ScheduledJobModel,
)
from geekvpn.infrastructure.persistence.models.payments import (
    CardAccountModel,
    InvoiceModel,
    PaymentModel,
    ReceiptDigestModel,
    RefundModel,
    WalletEntryModel,
)
from geekvpn.infrastructure.persistence.models.provisioning import (
    FunnelEventModel,
    NodeModel,
    OrderModel,
    ReferralModel,
    SubscriptionModel,
)
from geekvpn.infrastructure.persistence.models.settings import SettingModel
from geekvpn.infrastructure.persistence.models.support import (
    ReplyTemplateModel,
    TicketMessageModel,
    TicketModel,
)

__all__ = [
    "AdminModel",
    "AuditLogModel",
    "BroadcastModel",
    "CampaignModel",
    "CardAccountModel",
    "CategoryModel",
    "CouponModel",
    "CouponRedemptionModel",
    "FunnelEventModel",
    "InvoiceModel",
    "NodeModel",
    "NotificationModel",
    "NotificationPreferenceModel",
    "OrderModel",
    "PaymentModel",
    "PlanModel",
    "ProductModel",
    "ReceiptDigestModel",
    "ReferralModel",
    "RefreshTokenModel",
    "RefundModel",
    "ReplyTemplateModel",
    "ScheduledJobModel",
    "SessionModel",
    "SettingModel",
    "SubscriptionModel",
    "TicketMessageModel",
    "TicketModel",
    "UserModel",
    "WalletEntryModel",
]
