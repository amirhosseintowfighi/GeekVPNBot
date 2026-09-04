"""Marzban adapter.

Marzban is PasarGuard's ancestor and the two APIs are close cousins, but they
are NOT identical and must not share an implementation: Marzban grants access
via `inbounds`/`proxies` rather than groups, has no `/api/user/{u}/reset`
semantics identical to V5, and its `/api/users` envelope differs. Attempting to
share code between them would produce a class riddled with `if self.kind ==`,
which is exactly the design the plugin architecture exists to prevent.

Auth: OAuth2 password grant at `/api/admin/token`.
Units: bytes for traffic; `expire` is epoch seconds.
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
    BULK_PAGE,
    LOOKUP_PAGE,
    now_utc,
    require_a_readable_link,
    require_mapping,
    required_int,
    sub_token,
    subscription_of,
    to_int,
    to_utc,
)
from geekvpn.infrastructure.panels.base import HttpPanelAdapter
from geekvpn.infrastructure.panels.config import MarzbanConfig
from geekvpn.infrastructure.panels.registry import register_panel

_STATE_MAP = {
    "active": AccountState.ACTIVE,
    "on_hold": AccountState.ACTIVE,
    "disabled": AccountState.SUSPENDED,
    "expired": AccountState.EXPIRED,
    "limited": AccountState.QUOTA_EXHAUSTED,
}

#: Protocols Marzban expects as `proxies` keys when creating a user.
_DEFAULT_PROXIES: dict[str, dict[str, str]] = {"vless": {}, "vmess": {}}


@register_panel(
    PanelKind.MARZBAN,
    config=MarzbanConfig,
    description="Gozargah Marzban panel.",
)
class MarzbanAdapter(HttpPanelAdapter):
    """Adapter for Marzban."""

    kind: ClassVar[PanelKind] = PanelKind.MARZBAN
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

    _config: MarzbanConfig

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

    async def health(self) -> PanelHealth:
        started = now_utc()
        try:
            response = await self._http.request(
                "GET", "/api/system", headers=await self._auth_headers(), expected=(200,)
            )
            body = require_mapping(self._http.json(response), panel=self.kind.value, what="system")
        except Exception as exc:
            return PanelHealth(is_healthy=False, message=str(exc))
        return PanelHealth(
            is_healthy=True,
            latency_ms=(now_utc() - started).total_seconds() * 1000,
            version=str(body.get("version") or "") or None,
        )

    async def create_account(self, spec: AccountSpec, *, idempotency_key: str) -> PanelAccount:
        body: dict[str, Any] = {
            "username": spec.username,
            "status": "active",
            "data_limit": spec.quota.total_bytes or 0,
            "data_limit_reset_strategy": "no_reset",
            "proxies": dict(_DEFAULT_PROXIES),
            "note": spec.note or "",
        }
        # Always send expire. Marzban reads null as "leave unchanged", so omitting
        # the field on a never-expiring account hands the decision to whatever the
        # panel defaults to; only an explicit 0 means "no expiry".
        body["expire"] = int(spec.expires_at.timestamp()) if spec.expires_at is not None else 0
        if spec.group_tags:
            # An order-level tag list is not protocol-aware, so it applies to every
            # protocol we provision.
            body["inbounds"] = {proto: list(spec.group_tags) for proto in body["proxies"]}
        elif self._config.default_inbounds:
            body["inbounds"] = {
                proto: list(tags) for proto, tags in self._config.default_inbounds.items()
            }

        response = await self._http.request(
            "POST",
            "/api/user",
            json=body,
            headers=await self._auth_headers(),
            expected=(200, 201),
            allow_status=(409,),
        )
        if response.status_code == 409:
            existing = await self.get_account(self.ref(spec.username))
            # Both sides normalised. Unlimited is None here and 0 on the
            # right, so `None == 0` made the 409 retry fail for every
            # unlimited plan - the one case where retrying is guaranteed
            # correct, because the account already matches what we wanted.
            if (existing.usage.quota.total_bytes or 0) == (spec.quota.total_bytes or 0):
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
        await self._http.request(
            "DELETE",
            f"/api/user/{ref.username}",
            headers=await self._auth_headers(),
            expected=(200, 204),
            allow_status=(404,),
        )

    async def suspend(self, ref: PanelAccountRef, *, idempotency_key: str) -> PanelAccount:
        return await self._modify(ref, {"status": "disabled"})

    async def resume(self, ref: PanelAccountRef, *, idempotency_key: str) -> PanelAccount:
        return await self._modify(ref, {"status": "active"})

    async def _modify(self, ref: PanelAccountRef, body: Mapping[str, Any]) -> PanelAccount:
        response = await self._http.request(
            "PUT",
            f"/api/user/{ref.username}",
            json=dict(body),
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
            base = max(current.expires_at or now_utc(), now_utc())
            body["expire"] = int((base + extend_by).timestamp())
        if new_quota is not None:
            body["data_limit"] = new_quota.total_bytes or 0
        if not body:
            return await self.get_account(ref)
        return await self._modify(ref, body)

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

    async def find_by_subscription(self, url: str) -> PanelAccount | None:
        """Match a pasted link against this panel's own subscription URLs.

        For the customer who bought through support and now wants the bot to
        manage it. Compared on the token rather than the whole link - see
        `sub_token` for why the hostname cannot be trusted to match.
        """
        wanted = sub_token(url)
        if not wanted:
            return None
        response = await self._http.request(
            "GET",
            "/api/users",
            params={"limit": LOOKUP_PAGE},
            headers=await self._auth_headers(),
            expected=(200,),
        )
        payload = self._http.json(response)
        rows = payload.get("users") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            # Not "no match" - we could not read the reply at all. Returning
            # `None` here told a customer holding a working link that no such
            # subscription existed, which is the wrong sentence and points them
            # at the wrong thing to check.
            raise PanelContractViolation(
                "Account list was not readable.", panel=self.kind.value, envelope="users"
            )
        with_link = 0
        for row in rows:
            item = require_mapping(row, panel=self.kind.value, what="user")
            link = subscription_of(item)
            if link:
                with_link += 1
            if sub_token(link) == wanted:
                return self._to_account(item)
        # Only now is "not found" an honest answer.
        require_a_readable_link(len(rows), with_link, panel=self.kind.value)
        return None

    async def bulk_usage(self, refs: Sequence[PanelAccountRef]) -> Mapping[str, AccountUsage]:
        self.require(Capability.BULK_USAGE)
        wanted = {r.username for r in refs}
        if not wanted:
            return {}
        response = await self._http.request(
            "GET",
            "/api/users",
            params={"limit": max(len(wanted), BULK_PAGE)},
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
        return [
            NodeInfo(
                name=str(item.get("name", "")),
                address=str(item.get("address", "")),
                is_healthy=str(item.get("status", "")).lower() == "connected",
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
            used_bytes=required_int(item, "used_traffic", panel=self.kind.value),
            measured_at=now_utc(),
            # The panel's own last-seen. Absent on older builds, which
            # is why it is optional rather than defaulted to now.
            online_at=to_utc(item.get("online_at"), panel=self.kind.value, field="online_at"),
            quota=TrafficQuota(
                to_int(item.get("data_limit"), panel=self.kind.value, field="data_limit") or None
            ),
        )

    def _to_account(self, payload: Any) -> PanelAccount:
        item = require_mapping(payload, panel=self.kind.value, what="user")
        username = str(item.get("username", ""))
        if not username:
            raise PanelContractViolation("User payload had no username.", panel=self.kind.value)
        links = item.get("links") or []
        return PanelAccount(
            ref=self.ref(username),
            state=_STATE_MAP.get(str(item.get("status", "")).lower(), AccountState.UNKNOWN),
            usage=self._to_usage(item),
            expires_at=to_utc(item.get("expire"), panel=self.kind.value, field="expire"),
            subscription_url=item.get("subscription_url"),
            links=tuple(str(link) for link in links) if isinstance(links, list) else (),
        )
