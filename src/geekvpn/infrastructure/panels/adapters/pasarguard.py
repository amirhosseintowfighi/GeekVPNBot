"""PasarGuard V5 adapter.

PasarGuard is the panel this platform is being built against first, so this
adapter is the reference implementation: every other adapter should be read
against it.

API shape (V5): OAuth2 password grant at `/api/admin/token` returning a bearer
token, then first-class user resources under `/api/user/{username}`. Access is
granted through *groups*. The panel is a Python/FastAPI application, so it
returns proper JSON and correct status codes - which is why this adapter is the
simplest of the five.

Units: PasarGuard reports `used_traffic` and `data_limit` in **bytes**, and
expiry as an epoch or ISO string depending on endpoint, both handled by
`_common.to_utc`.
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
from geekvpn.infrastructure.panels.config import PasarGuardConfig
from geekvpn.infrastructure.panels.registry import register_panel

#: PasarGuard status strings -> our five states.
_STATE_MAP = {
    "active": AccountState.ACTIVE,
    "on_hold": AccountState.ACTIVE,
    "disabled": AccountState.SUSPENDED,
    "expired": AccountState.EXPIRED,
    "limited": AccountState.QUOTA_EXHAUSTED,
}


@register_panel(
    PanelKind.PASARGUARD,
    config=PasarGuardConfig,
    description="PasarGuard V5 panel (Xray + WireGuard).",
)
class PasarGuardAdapter(HttpPanelAdapter):
    """Adapter for PasarGuard V5."""

    kind: ClassVar[PanelKind] = PanelKind.PASARGUARD
    capabilities: ClassVar[frozenset[Capability]] = frozenset(
        {
            Capability.RESET_TRAFFIC,
            Capability.NATIVE_EXPIRY_EXTEND,
            Capability.NATIVE_QUOTA_EXTEND,
            Capability.BULK_USAGE,
            Capability.NODE_INVENTORY,
            Capability.PER_NODE_ASSIGNMENT,
            Capability.SUBSCRIPTION_URL,
            Capability.DEVICE_LIMIT,
        }
    )

    _config: PasarGuardConfig

    # -- auth --------------------------------------------------------------

    async def _login(self) -> tuple[str, timedelta | None]:
        response = await self._http.request(
            "POST",
            "/api/admin/token",
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

    # -- health ------------------------------------------------------------

    async def health(self) -> PanelHealth:
        started = now_utc()
        try:
            response = await self._http.request(
                "GET", "/api/system", headers=await self._auth_headers(), expected=(200,)
            )
            body = require_mapping(self._http.json(response), panel=self.kind.value, what="system")
        except Exception as exc:
            return PanelHealth(is_healthy=False, message=str(exc))
        elapsed = (now_utc() - started).total_seconds() * 1000
        return PanelHealth(
            is_healthy=True,
            latency_ms=elapsed,
            version=str(body.get("version") or "") or None,
        )

    # -- accounts ----------------------------------------------------------

    async def create_account(self, spec: AccountSpec, *, idempotency_key: str) -> PanelAccount:
        body: dict[str, Any] = {
            "username": spec.username,
            "status": "active",
            "data_limit": spec.quota.total_bytes or 0,
            "data_limit_reset_strategy": "no_reset",
            "note": spec.note or "",
        }
        if spec.expires_at is not None:
            body["expire"] = int(spec.expires_at.timestamp())
        groups = spec.group_tags or self._config.default_groups
        if groups:
            body["group_ids"] = list(groups)
        if spec.device_limit is not None:
            body["ip_limit"] = spec.device_limit

        response = await self._http.request(
            "POST",
            "/api/user",
            json=body,
            headers=await self._auth_headers(),
            expected=(200, 201),
            allow_status=(409,),
        )
        if response.status_code == 409:
            # A retry of a create that already landed. Re-read rather than fail:
            # the customer's money has been taken, they need their account.
            existing = await self.get_account(self.ref(spec.username))
            if existing.usage.quota.total_bytes == (spec.quota.total_bytes or 0):
                return existing
            raise AccountAlreadyExists(panel=self.kind.value, username=spec.username)
        return self._to_account(self._http.json(response))

    async def get_account(self, ref: PanelAccountRef) -> PanelAccount:
        response = await self._http.request(
            "GET",
            f"/api/user/{ref.username}",
            headers=await self._auth_headers(),
            expected=(200,),
            allow_status=(404,),
        )
        if response.status_code == 404:
            raise AccountNotFound(panel=self.kind.value, username=ref.username)
        return self._to_account(self._http.json(response))

    async def delete_account(self, ref: PanelAccountRef, *, idempotency_key: str) -> None:
        # 404 tolerated: a retried delete must be a success, not an error.
        await self._http.request(
            "DELETE",
            f"/api/user/{ref.username}",
            headers=await self._auth_headers(),
            expected=(200, 204),
            allow_status=(404,),
        )

    async def suspend(self, ref: PanelAccountRef, *, idempotency_key: str) -> PanelAccount:
        return await self._set_status(ref, "disabled")

    async def resume(self, ref: PanelAccountRef, *, idempotency_key: str) -> PanelAccount:
        return await self._set_status(ref, "active")

    async def _set_status(self, ref: PanelAccountRef, status: str) -> PanelAccount:
        response = await self._http.request(
            "PUT",
            f"/api/user/{ref.username}",
            json={"status": status},
            headers=await self._auth_headers(),
            expected=(200,),
            allow_status=(404,),
        )
        if response.status_code == 404:
            raise AccountNotFound(panel=self.kind.value, username=ref.username)
        return self._to_account(self._http.json(response))

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
            body["expire"] = int(new_expires_at.timestamp())
        elif extend_by is not None:
            current = await self.get_account(ref)
            # Extend from whichever is later: an expired account must get the
            # full period it was paid for, not a window that already elapsed.
            base = max(current.expires_at or now_utc(), now_utc())
            body["expire"] = int((base + extend_by).timestamp())
        if new_quota is not None:
            body["data_limit"] = new_quota.total_bytes or 0
        if not body:
            return await self.get_account(ref)

        response = await self._http.request(
            "PUT",
            f"/api/user/{ref.username}",
            json=body,
            headers=await self._auth_headers(),
            expected=(200,),
            allow_status=(404,),
        )
        if response.status_code == 404:
            raise AccountNotFound(panel=self.kind.value, username=ref.username)
        return self._to_account(self._http.json(response))

    # -- capabilities ------------------------------------------------------

    async def reset_traffic(self, ref: PanelAccountRef, *, idempotency_key: str) -> PanelAccount:
        self.require(Capability.RESET_TRAFFIC)
        response = await self._http.request(
            "POST",
            f"/api/user/{ref.username}/reset",
            headers=await self._auth_headers(),
            expected=(200,),
            allow_status=(404,),
        )
        if response.status_code == 404:
            raise AccountNotFound(panel=self.kind.value, username=ref.username)
        return self._to_account(self._http.json(response))

    async def bulk_usage(self, refs: Sequence[PanelAccountRef]) -> Mapping[str, AccountUsage]:
        self.require(Capability.BULK_USAGE)
        wanted = {r.username for r in refs}
        if not wanted:
            return {}
        response = await self._http.request(
            "GET",
            "/api/users",
            params={"limit": max(len(wanted), 100)},
            headers=await self._auth_headers(),
            expected=(200,),
        )
        payload = self._http.json(response)
        rows = payload.get("users") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise PanelContractViolation(
                "Bulk usage response was not a list.", panel=self.kind.value
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
        rows = payload if isinstance(payload, list) else payload.get("nodes", [])
        result: list[NodeInfo] = []
        for row in rows:
            item = require_mapping(row, panel=self.kind.value, what="node")
            result.append(
                NodeInfo(
                    name=str(item.get("name", "")),
                    address=str(item.get("address", "")),
                    is_healthy=str(item.get("status", "")).lower() == "connected",
                    external_id=str(item["id"]) if item.get("id") is not None else None,
                    xray_version=item.get("xray_version"),
                    message=item.get("message"),
                )
            )
        return result

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

    # -- mapping -----------------------------------------------------------

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
        raw_status = str(item.get("status", "")).lower()
        links = item.get("links") or []
        return PanelAccount(
            ref=self.ref(username),
            state=_STATE_MAP.get(raw_status, AccountState.UNKNOWN),
            usage=self._to_usage(item),
            expires_at=to_utc(item.get("expire"), panel=self.kind.value, field="expire"),
            subscription_url=item.get("subscription_url"),
            links=tuple(str(link) for link in links) if isinstance(links, list) else (),
        )
