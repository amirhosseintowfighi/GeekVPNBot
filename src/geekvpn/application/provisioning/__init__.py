"""The order and provisioning application layer.

Phase 4 built the catalog, Phase 8 built payments, and Phase 3 built the panel
adapters - but nothing joined them. This package is the join: it places orders,
moves them to PAID when money is captured, and turns a paid order into a working
account on a panel.
"""

from geekvpn.application.provisioning.node_selector import eligible_nodes, select_node
from geekvpn.application.provisioning.order_service import (
    INVOICE_ORDER_KEY,
    OrderPaymentBridge,
    OrderService,
)
from geekvpn.application.provisioning.ports import (
    EventPublisher,
    IdGenerator,
    NodeRecord,
    NodeRepository,
    OrderNumberGenerator,
    OrderRepository,
    PanelProvider,
    SubscriptionRepository,
    SyncOrderRepository,
)
from geekvpn.application.provisioning.provisioning_service import (
    BYTES_PER_MIB,
    ProvisioningService,
    panel_id_for,
    username_for,
)

__all__ = [
    "BYTES_PER_MIB",
    "INVOICE_ORDER_KEY",
    "EventPublisher",
    "IdGenerator",
    "NodeRecord",
    "NodeRepository",
    "OrderNumberGenerator",
    "OrderPaymentBridge",
    "OrderRepository",
    "OrderService",
    "PanelProvider",
    "ProvisioningService",
    "SubscriptionRepository",
    "SyncOrderRepository",
    "eligible_nodes",
    "panel_id_for",
    "select_node",
    "username_for",
]
