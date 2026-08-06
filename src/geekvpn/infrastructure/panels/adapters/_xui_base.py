"""Shared implementation for the x-ui lineage (3x-ui and x-ui).

These two panels are genuine forks of one codebase and their APIs are the same
shape: cookie-session login, a `{"success", "msg", "obj"}` envelope, and clients
stored as a **JSON string** inside an inbound's `settings` field.

So unlike Marzban/Marzneshin, sharing here is correct. The variation between
them is expressed purely as **class attributes** (path prefixes), never as
runtime conditionals - a template method, not a switch. If a fork ever diverges
behaviourally, it overrides a method and the others are unaffected.

The hard part of this family is that there is no "user" resource. Creating a
subscription means:

1. read the inbound,
2. parse its `settings` JSON string,
3. splice a client into the `clients` array,
4. write the whole thing back.

That is a read-modify-write over a shared document, so two concurrent
provisionings against the same inbound can lose one another. `addClient` is
used where available precisely because it pushes that merge server-side.
"""

from __future__ import annotations

import json
import uuid as uuid_module
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, ClassVar

from geekvpn.domain.panels.enums import AccountState, Capability, PanelKind
from geekvpn.domain.panels.errors import (
    AccountAlreadyExists,
    AccountNotFound,
    PanelContractViolation,
)
from geekvpn.domain.panels.values import (
    AccountSpec,
    AccountUsage,
    PanelAccount,
    PanelAccountRef,
    PanelHealth,
    TrafficQuota,
)
from geekvpn.infrastructure.panels.adapters._common import now_utc, require_mapping, to_int
from geekvpn.infrastructure.panels.base import HttpPanelAdapter
from geekvpn.infrastructure.panels.config import XuiFamilyConfig


class XuiFamilyAdapter(HttpPanelAdapter):
    """Template for cookie-authenticated, inbound-nested panels."""

    kind: ClassVar[PanelKind]
    capabilities: ClassVar[frozenset[Capability]] = frozenset(
        {
            Capability.RESET_TRAFFIC,
            Capability.NATIVE_EXPIRY_EXTEND,
            Capability.NATIVE_QUOTA_EXTEND,
            Capability.DEVICE_LIMIT,
        }
    )

    #: Subclass hooks. The ONLY thing that differs between these panels.
    login_path: ClassVar[str] = "/login"
    api_prefix: ClassVar[str] = "/panel/api/inbounds"

    _config: XuiFamilyConfig

    # -- paths -------------------------------------------------------------

    def _url(self, suffix: str) -> str:
        return f"{self._config.web_base_path}{self.api_prefix}{suffix}"

    # -- auth --------------------------------------------------------------

    async def _login(self) -> tuple[str, timedelta | None]:
        """Authenticate and keep the session cookie on the shared client.

        This family does not issue bearer tokens, so we return a sentinel and
        rely on the cookie jar. The token-cache machinery in the base class
        still gives us "log in only when needed", which is what we want.
        """
        response = await self._http.request(
            "POST",
            f"{self._config.web_base_path}{self.login_path}",
            data={
                "username": self._config.username,
                "password": self._config.password.get_secret_value(),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            expected=(200,),
        )
        body = self._envelope(response, what="login")
        if body is False:
            raise PanelContractViolation("Login was rejected.", panel=self.kind.value)
        return "cookie-session", timedelta(hours=1)

    async def _auth_headers(self) -> dict[str, str]:
        """Ensure a live session, but send no Authorization header."""
        await self._bearer()
        return {}

    # -- envelope ----------------------------------------------------------

    def _envelope(self, response: Any, *, what: str) -> Any:
        """Unwrap `{"success": bool, "msg": str, "obj": ...}`.

        This family returns HTTP 200 for logical failures, so the status code
        alone is not a success signal. Ignoring `success` here would let a
        failed provisioning look like a completed one.
        """
        payload = require_mapping(self._http.json(response), panel=self.kind.value, what=what)
        if not payload.get("success", False):
            message = str(payload.get("msg", "")).strip()
            if "exist" in message.lower():
                raise AccountAlreadyExists(message, panel=self.kind.value)
            raise PanelContractViolation(
                message or f"Panel reported failure for {what}.", panel=self.kind.value
            )
        return payload.get("obj")

    # -- health ------------------------------------------------------------

    async def health(self) -> PanelHealth:
        started = now_utc()
        try:
            await self._auth_headers()
            response = await self._http.request("GET", self._url("/list"), expected=(200,))
            self._envelope(response, what="inbound list")
        except Exception as exc:
            return PanelHealth(is_healthy=False, message=str(exc))
        return PanelHealth(is_healthy=True, latency_ms=(now_utc() - started).total_seconds() * 1000)

    # -- inbound document --------------------------------------------------

    async def _inbound(self) -> dict[str, Any]:
        await self._auth_headers()
        response = await self._http.request(
            "GET",
            self._url(f"/get/{self._config.inbound_id}"),
            expected=(200,),
            allow_status=(404,),
        )
        if response.status_code == 404:
            raise PanelContractViolation(
                f"Inbound {self._config.inbound_id} does not exist.",
                panel=self.kind.value,
            )
        return require_mapping(
            self._envelope(response, what="inbound"), panel=self.kind.value, what="inbound"
        )

    def _clients(self, inbound: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Extract the clients array from the inbound's stringified settings."""
        raw = inbound.get("settings")
        if isinstance(raw, str):
            try:
                settings = json.loads(raw or "{}")
            except ValueError as exc:
                raise PanelContractViolation(
                    "Inbound settings were not valid JSON.", panel=self.kind.value
                ) from exc
        elif isinstance(raw, dict):
            settings = raw
        else:
            settings = {}
        clients = settings.get("clients", [])
        return clients if isinstance(clients, list) else []

    def _find_client(self, inbound: Mapping[str, Any], username: str) -> dict[str, Any] | None:
        for client in self._clients(inbound):
            if isinstance(client, dict) and client.get("email") == username:
                return client
        return None

    # -- accounts ----------------------------------------------------------

    async def create_account(self, spec: AccountSpec, *, idempotency_key: str) -> PanelAccount:
        inbound = await self._inbound()
        if self._find_client(inbound, spec.username) is not None:
            # Retried create. Return the live account rather than erroring.
            return await self.get_account(self.ref(spec.username))

        client: dict[str, Any] = {
            "id": str(uuid_module.uuid4()),
            "email": spec.username,
            "enable": True,
            "totalGB": spec.quota.total_bytes or 0,
            "expiryTime": (int(spec.expires_at.timestamp() * 1000) if spec.expires_at else 0),
            "limitIp": spec.device_limit or 0,
            "tgId": "",
            "subId": spec.username,
            "flow": "",
        }
        await self._http.request(
            "POST",
            self._url("/addClient"),
            json={
                "id": self._config.inbound_id,
                "settings": json.dumps({"clients": [client]}),
            },
            expected=(200,),
        )
        return await self.get_account(self.ref(spec.username, external_id=client["id"]))

    async def get_account(self, ref: PanelAccountRef) -> PanelAccount:
        inbound = await self._inbound()
        client = self._find_client(inbound, ref.username)
        if client is None:
            raise AccountNotFound(panel=self.kind.value, username=ref.username)
        return self._to_account(client, await self._traffic(ref.username))

    async def _traffic(self, username: str) -> dict[str, Any]:
        """Per-client counters live on a separate endpoint from the client object."""
        await self._auth_headers()
        response = await self._http.request(
            "GET",
            self._url(f"/getClientTraffics/{username}"),
            expected=(200,),
            allow_status=(404,),
        )
        if response.status_code == 404:
            return {}
        obj = self._envelope(response, what="client traffic")
        return obj if isinstance(obj, dict) else {}

    async def delete_account(self, ref: PanelAccountRef, *, idempotency_key: str) -> None:
        client_id = ref.external_id
        if client_id is None:
            try:
                inbound = await self._inbound()
            except PanelContractViolation:
                # The inbound itself is gone, so the client inside it certainly is
                # too. Delete is the one operation that must be safe to retry:
                # compensating transactions rerun it, and raising here would wedge
                # every rollback that follows a panel being rebuilt.
                return
            found = self._find_client(inbound, ref.username)
            if found is None:
                return  # Already gone; a retried delete must succeed.
            client_id = str(found.get("id", ""))
        await self._auth_headers()
        await self._http.request(
            "POST",
            self._url(f"/{self._config.inbound_id}/delClient/{client_id}"),
            expected=(200,),
            allow_status=(404,),
        )

    async def suspend(self, ref: PanelAccountRef, *, idempotency_key: str) -> PanelAccount:
        return await self._patch_client(ref, {"enable": False})

    async def resume(self, ref: PanelAccountRef, *, idempotency_key: str) -> PanelAccount:
        return await self._patch_client(ref, {"enable": True})

    async def _patch_client(self, ref: PanelAccountRef, changes: Mapping[str, Any]) -> PanelAccount:
        """Read-modify-write a single client.

        The panel has no partial-update endpoint, so we must resend the whole
        client object. We merge onto the *current* server state rather than a
        cached copy, which keeps a concurrent change from being silently undone.
        """
        inbound = await self._inbound()
        client = self._find_client(inbound, ref.username)
        if client is None:
            raise AccountNotFound(panel=self.kind.value, username=ref.username)
        updated = {**client, **changes}
        await self._auth_headers()
        await self._http.request(
            "POST",
            self._url(f"/updateClient/{updated['id']}"),
            json={
                "id": self._config.inbound_id,
                "settings": json.dumps({"clients": [updated]}),
            },
            expected=(200,),
        )
        return self._to_account(updated, await self._traffic(ref.username))

    async def usage(self, ref: PanelAccountRef) -> AccountUsage:
        stats = await self._traffic(ref.username)
        if not stats:
            raise AccountNotFound(panel=self.kind.value, username=ref.username)
        return self._to_usage(stats)

    async def renew(
        self,
        ref: PanelAccountRef,
        *,
        extend_by: timedelta | None = None,
        new_expires_at: datetime | None = None,
        new_quota: TrafficQuota | None = None,
        idempotency_key: str,
    ) -> PanelAccount:
        changes: dict[str, Any] = {}
        if new_expires_at is not None:
            changes["expiryTime"] = int(new_expires_at.timestamp() * 1000)
        elif extend_by is not None:
            current = await self.get_account(ref)
            base = max(current.expires_at or now_utc(), now_utc())
            changes["expiryTime"] = int((base + extend_by).timestamp() * 1000)
        if new_quota is not None:
            changes["totalGB"] = new_quota.total_bytes or 0
        if not changes:
            return await self.get_account(ref)
        return await self._patch_client(ref, changes)

    async def reset_traffic(self, ref: PanelAccountRef, *, idempotency_key: str) -> PanelAccount:
        self.require(Capability.RESET_TRAFFIC)
        await self._auth_headers()
        await self._http.request(
            "POST",
            self._url(f"/{self._config.inbound_id}/resetClientTraffic/{ref.username}"),
            expected=(200,),
            allow_status=(404,),
        )
        return await self.get_account(ref)

    # -- mapping -----------------------------------------------------------

    def _to_usage(self, stats: Mapping[str, Any]) -> AccountUsage:
        """This family splits usage into `up` and `down`; bill the sum."""
        up = to_int(stats.get("up"), panel=self.kind.value, field="up")
        down = to_int(stats.get("down"), panel=self.kind.value, field="down")
        # `total` is the CAP in this family, despite the name. Naming this
        # wrong is the single most common bug in x-ui integrations.
        cap = to_int(stats.get("total"), panel=self.kind.value, field="total")
        return AccountUsage(
            used_bytes=up + down,
            measured_at=now_utc(),
            quota=TrafficQuota(cap or None),
        )

    def _to_account(self, client: Mapping[str, Any], stats: Mapping[str, Any]) -> PanelAccount:
        username = str(client.get("email", ""))
        if not username:
            raise PanelContractViolation("Client had no email field.", panel=self.kind.value)
        usage = self._to_usage(
            stats
            or {
                "up": 0,
                "down": 0,
                "total": to_int(client.get("totalGB"), panel=self.kind.value, field="totalGB"),
            }
        )
        expiry_ms = to_int(client.get("expiryTime"), panel=self.kind.value, field="expiryTime")
        expires_at = (
            datetime.fromtimestamp(expiry_ms / 1000, tz=now_utc().tzinfo) if expiry_ms > 0 else None
        )

        if client.get("enable") is False:
            state = AccountState.SUSPENDED
        elif expires_at is not None and expires_at <= now_utc():
            state = AccountState.EXPIRED
        elif usage.quota.total_bytes and usage.used_bytes >= usage.quota.total_bytes:
            state = AccountState.QUOTA_EXHAUSTED
        else:
            state = AccountState.ACTIVE

        return PanelAccount(
            ref=self.ref(username, external_id=str(client.get("id") or "") or None),
            state=state,
            usage=usage,
            expires_at=expires_at,
        )

    async def bulk_usage(self, refs: Sequence[PanelAccountRef]) -> Mapping[str, AccountUsage]:
        self.require(Capability.BULK_USAGE)
        raise NotImplementedError  # pragma: no cover
