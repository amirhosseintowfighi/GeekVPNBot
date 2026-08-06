"""Concrete analytics adapters."""

from __future__ import annotations

from geekvpn.infrastructure.analytics.sql_readers import (
    SqlCampaignAnalyticsReader,
    SqlCustomerReader,
    SqlFunnelReader,
    SqlNodeReader,
    SqlReferralReader,
    SqlRetentionReader,
    SqlRevenueReader,
    SqlWorkQueueReader,
    build_readers,
)

__all__ = [
    "SqlCampaignAnalyticsReader",
    "SqlCustomerReader",
    "SqlFunnelReader",
    "SqlNodeReader",
    "SqlReferralReader",
    "SqlRetentionReader",
    "SqlRevenueReader",
    "SqlWorkQueueReader",
    "build_readers",
]
