"""Marzneshin adapter.

Marzneshin is a Marzban fork that rebuilt the access model: users are attached
to **services** (integer ids), not inbound tags, and the collection endpoint is
paginated under `/api/users` with an `items` envelope. It also exposes
`/api/users/{username}/enable` and `/disable` as explicit verbs rather than a
status field, and expiry is an ISO-8601 string rather than an epoch.

Those four differences are why this is its own adapter and not a Marzban
subclass. They are not cosmetic - sharing an implementation would mean four
conditionals on the hot path of every purchase.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, ClassVar

from geekvpn.domain.panels.enums import AccountState, Capability, PanelKind, SubscriptionFormat
from geekvpn.domain.panels.errors import (
    AccountAlreadyExists,
    AccountNotFound,
    PanelContractViolation,
)
from geekvpn.domain.panels.values import (
    AccountSpec,
    AccountUsage,
    NodeInfo,
    PanelAccount,
    PanelAccountRef,
    PanelHealth,
    SubscriptionPayload,
    TrafficQuota,
)
from geekvpn.infrastructure.panels.adapters._common import (
    now_utc,
    require_mapping,
    to_int,
    to_utc,
)
from geekvpn.infrastructure.panels.base import HttpPanelAdapter
from geekvpn.infrastructure.panels.config import MarzneshinConfig
from geekvpn.infrastructure.panels.registry import register_panel

_STATE_MAP = {
    "active": AccountState.ACTIVE,
    "on_hold": AccountState.ACTIVE,
    "disabled": AccountState.SUSPENDED,
    "expired": AccountState.EXPIRED,
    "limited": AccountState.QUOTA_EXHAUSTED,
}


@register_panel(
    PanelKind.MARZNESHIN,
    config=MarzneshinConfig,
    description="Marzneshin panel (service-based Marzban fork).",
)
class MarzneshinAdapter(HttpPanelAdapter):
    """Adapter for Marzneshin."""

    kind: ClassVar[PanelKind] = PanelKind.MARZNESHIN
    capabilities: ClassVar[frozenset[Capability]] = frozenset(
        {
            Capability.RESET_TRAFFIC,
            Capability.NATIVE_EXPIRY_EXTEND,
            Capability.NATIVE_QUOTA_EXTEND,
            Capability.BULK_USAGE,
            Capability.NODE_INVENTORY,
            Capability.SUBSCRIPTION_URL,
        }
    )

    _config: MarzneshinConfig

    async def _login(self) -> tuple[str, timedelta | None]:
        response = await self._http.request(
            "POST",
            "/api/admins/token",
            data={
                "grant_type": "password",
                "username": self._config.username,
                "password": self._config.password.get_secret_value(),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            expected=(200,),
        )
        payload = require_mapping(
            self._http.json(response), panel=self.kind.value, what="token response"
        )
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise PanelContractViolation(
                "Token response had no access_token.", panel=self.kind.value
            )
        return token, None

    async def health(self) -> PanelHealth:
        started = now_utc()
        try:
            response = await self._http.request(
                "GET",
                "/api/system/stats",
                headers=await self._auth_headers(),
                expected=(200,),
            )
            body = require_mapping(self._http.json(response), panel=self.kind.value, what="stats")
        except Exception as exc:
            return PanelHealth(is_healthy=False, message=str(exc))
        return PanelHealth(
            is_healthy=True,
            latency_ms=(now_utc() - started).total_seconds() * 1000,
            version=str(body.get("version") or "") or None,
        )

    async def create_account(self, spec: AccountSpec, *, idempotency_key: str) -> PanelAccount:
        services = (
            [int(t) for t in spec.group_tags] if spec.group_tags else list(self._config.service_ids)
        )
        body: dict[str, Any] = {
            "username": spec.username,
            "data_limit": spec.quota.total_bytes or 0,
            "data_limit_reset_strategy": "no_reset",
            "service_ids": services,
            "note": spec.note or "",
        }
        if spec.expires_at is not None:
            body["expire_strategy"] = "fixed_date"
            body["expire_date"] = spec.expires_at.isoformat()
        else:
            body["expire_strategy"] = "never"

        response = await self._http.request(
            "POST",
            "/api/users",
            json=body,
            headers=await self._auth_headers(),
            expected=(200, 201),
            allow_status=(409,),
        )
        if response.status_code == 409:
            existing = await self.get_account(self.ref(spec.username))
            if existing.usage.quota.total_bytes == (spec.quota.total_bytes or 0):
                return existing
            raise AccountAlreadyExists(panel=self.kind.value, username=spec.username)
        return self._to_account(self._http.json(response))

    async def get_account(self, ref: PanelAccountRef) -> PanelAccount:
        response = await self._http.request(
            "GET",
            f"/api/users/{ref.username}",
            headers=await self._auth_headers(),
            expected=(200,),
            allow_status=(404,),
        )
        if response.status_code == 404:
            raise AccountNotFound(panel=self.kind.value, username=ref.username)
        return self._to_account(self._http.json(response))

    async def delete_account(self, ref: PanelAccountRef, *, idempotency_key: str) -> None:
        await self._http.request(
            "DELETE",
            f"/api/users/{ref.username}",
            headers=await self._auth_headers(),
            expected=(200, 204),
            allow_status=(404,),
        )

    async def suspend(self, ref: PanelAccountRef, *, idempotency_key: str) -> PanelAccount:
        return await self._verb(ref, "disable")

    async def resume(self, ref: PanelAccountRef, *, idempotency_key: str) -> PanelAccount:
        return await self._verb(ref, "enable")

    async def _verb(self, ref: PanelAccountRef, verb: str) -> PanelAccount:
        """Marzneshin models enable/disable as sub-resources, not status writes."""
        response = await self._http.request(
            "POST",
            f"/api/users/{ref.username}/{verb}",
            headers=await self._auth_headers(),
            expected=(200, 204),
            allow_status=(404,),
        )
        if response.status_code == 404:
            raise AccountNotFound(panel=self.kind.value, username=ref.username)
        # The verb endpoints return no useful body; re-read for a truthful view.
        return await self.get_account(ref)

    async def usage(self, ref: PanelAccountRef) -> AccountUsage:
        return (await self.get_account(ref)).usage

    async def renew(
        self,
        ref: PanelAccountRef,
        *,
        extend_by: timedelta | None = None,
        new_expires_at: datetime | None = None,
        new_quota: TrafficQuota | None = None,
        idempotency_key: str,
    ) -> PanelAccount:
        body: dict[str, Any] = {}
        if new_expires_at is not None:
            body["expire_strategy"] = "fixed_date"
            body["expire_date"] = new_expires_at.isoformat()
        elif extend_by is not None:
            current = await self.get_account(ref)
            base = max(current.expires_at or now_utc(), now_utc())
            body["expire_strategy"] = "fixed_date"
            body["expire_date"] = (base + extend_by).isoformat()
        if new_quota is not None:
            body["data_limit"] = new_quota.total_bytes or 0
        if not body:
            return await self.get_account(ref)

        response = await self._http.request(
            "PUT",
            f"/api/users/{ref.username}",
            json=body,
            headers=await self._auth_headers(),
            expected=(200,),
            allow_status=(404,),
        )
        if response.status_code == 404:
            raise AccountNotFound(panel=self.kind.value, username=ref.username)
        return self._to_account(self._http.json(response))

    async def reset_traffic(self, ref: PanelAccountRef, *, idempotency_key: str) -> PanelAccount:
        self.require(Capability.RESET_TRAFFIC)
        response = await self._http.request(
            "POST",
            f"/api/users/{ref.username}/reset",
            headers=await self._auth_headers(),
            expected=(200, 204),
            allow_status=(404,),
        )
        if response.status_code == 404:
            raise AccountNotFound(panel=self.kind.value, username=ref.username)
        return await self.get_account(ref)

    async def bulk_usage(self, refs: Sequence[PanelAccountRef]) -> Mapping[str, AccountUsage]:
        self.require(Capability.BULK_USAGE)
        wanted = {r.username for r in refs}
        if not wanted:
            return {}
        response = await self._http.request(
            "GET",
            "/api/users",
            params={"size": max(len(wanted), 100), "page": 1},
            headers=await self._auth_headers(),
            expected=(200,),
        )
        payload = self._http.json(response)
        # Marzneshin paginates with an `items` envelope.
        rows = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise PanelContractViolation(
                "Bulk usage response had no items list.", panel=self.kind.value
            )
        out: dict[str, AccountUsage] = {}
        for row in rows:
            item = require_mapping(row, panel=self.kind.value, what="user")
            name = str(item.get("username", ""))
            if name in wanted:
                out[name] = self._to_usage(item)
        return out

    async def nodes(self) -> Sequence[NodeInfo]:
        self.require(Capability.NODE_INVENTORY)
        response = await self._http.request(
            "GET", "/api/nodes", headers=await self._auth_headers(), expected=(200,)
        )
        payload = self._http.json(response)
        rows = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            rows = []
        return [
            NodeInfo(
                name=str(item.get("name", "")),
                address=str(item.get("address", "")),
                is_healthy=str(item.get("status", "")).lower() in {"healthy", "connected"},
                external_id=str(item["id"]) if item.get("id") is not None else None,
                xray_version=item.get("xray_version"),
                message=item.get("message"),
            )
            for item in (require_mapping(r, panel=self.kind.value, what="node") for r in rows)
        ]

    async def subscription(
        self, ref: PanelAccountRef, *, fmt: SubscriptionFormat = SubscriptionFormat.AUTO
    ) -> SubscriptionPayload:
        self.require(Capability.SUBSCRIPTION_URL)
        account = await self.get_account(ref)
        if not account.subscription_url:
            raise PanelContractViolation(
                "Panel did not return a subscription URL.", panel=self.kind.value
            )
        return SubscriptionPayload(
            content=account.subscription_url, content_type="text/uri-list", fmt=fmt
        )

    def _to_usage(self, item: Mapping[str, Any]) -> AccountUsage:
        return AccountUsage(
            used_bytes=to_int(
                item.get("used_traffic"), panel=self.kind.value, field="used_traffic"
            ),
            measured_at=now_utc(),
            quota=TrafficQuota(
                to_int(item.get("data_limit"), panel=self.kind.value, field="data_limit") or None
            ),
        )

    def _to_account(self, payload: Any) -> PanelAccount:
        item = require_mapping(payload, panel=self.kind.value, what="user")
        username = str(item.get("username", ""))
        if not username:
            raise PanelContractViolation("User payload had no username.", panel=self.kind.value)
        # Marzneshin exposes both a coarse `is_active` flag and a finer
        # `expired`/`data_limit_reached` pair. Prefer the specific reason so the
        # bot can tell a customer *why* they are offline.
        if item.get("expired") is True:
            state = AccountState.EXPIRED
        elif item.get("data_limit_reached") is True:
            state = AccountState.QUOTA_EXHAUSTED
        elif item.get("enabled") is False or item.get("is_active") is False:
            state = AccountState.SUSPENDED
        else:
            state = _STATE_MAP.get(str(item.get("status", "active")).lower(), AccountState.ACTIVE)
        links = item.get("links") or []
        return PanelAccount(
            ref=self.ref(username),
            state=state,
            usage=self._to_usage(item),
            expires_at=to_utc(
                item.get("expire_date") or item.get("expire"),
                panel=self.kind.value,
                field="expire_date",
            ),
            subscription_url=item.get("subscription_url"),
            links=tuple(str(link) for link in links) if isinstance(links, list) else (),
        )
