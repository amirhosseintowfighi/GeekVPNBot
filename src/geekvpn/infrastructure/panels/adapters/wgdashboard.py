"""WGDashboard adapter.

WGDashboard manages plain WireGuard, and its model is not a user but a *peer*
inside one configuration ("wg0"): a key pair and an address. Everything a
subscription needs is mapped onto that:

* **The account is a peer named after our username.** Peers are addressed by
  their public key; the name is the only thing we choose, so lookups read the
  configuration's peer list and match on it.
* **Limits are the dashboard's own schedule jobs.** A job restricts the peer
  when its traffic passes a figure or when a date arrives - which is exactly a
  quota and an expiry, enforced by the dashboard even while we are down.
* **The customer's link is a share link.** WireGuard has no subscription
  document; the dashboard's share page hands the customer the config file and
  its QR code, which is what they import.
* **Suspend is "restrict".** A restricted peer stays configured but cannot
  connect, and "allow access" restores it - the same peer, the same key.

Units: the dashboard reports traffic in GB (1024³ bytes) as floats.
Auth: a static API key in the `wg-dashboard-apikey` header, no login.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlparse

from geekvpn.domain.panels.enums import AccountState, Capability, PanelKind, SubscriptionFormat
from geekvpn.domain.panels.errors import (
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
from geekvpn.infrastructure.panels.adapters._common import now_utc, require_mapping
from geekvpn.infrastructure.panels.base import HttpPanelAdapter
from geekvpn.infrastructure.panels.config import WgDashboardConfig
from geekvpn.infrastructure.panels.registry import register_panel

GIB = 1024**3
#: The dashboard's own date format for jobs and share links.
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
#: Job fields the dashboard understands.
TRAFFIC_FIELD = "total_data"
DATE_FIELD = "date"


@register_panel(
    PanelKind.WGDASHBOARD,
    config=WgDashboardConfig,
    description="WGDashboard (plain WireGuard peers).",
)
class WgDashboardAdapter(HttpPanelAdapter):
    """Adapter for WGDashboard v4."""

    kind: ClassVar[PanelKind] = PanelKind.WGDASHBOARD
    capabilities: ClassVar[frozenset[Capability]] = frozenset(
        {
            Capability.RESET_TRAFFIC,
            Capability.NATIVE_EXPIRY_EXTEND,
            Capability.NATIVE_QUOTA_EXTEND,
            Capability.BULK_USAGE,
            Capability.SUBSCRIPTION_URL,
        }
    )

    _config: WgDashboardConfig

    # -- transport ---------------------------------------------------------

    async def _auth_headers(self) -> dict[str, str]:
        # The node's password column carries the key: it is the encrypted one.
        key = self._config.api_key.get_secret_value() or self._config.password.get_secret_value()
        return {"wg-dashboard-apikey": key}

    @property
    def _configuration(self) -> str:
        return self._config.configuration

    async def _get(self, path: str, **params: Any) -> Any:
        response = await self._http.request(
            "GET", path, params=params, headers=await self._auth_headers(), expected=(200,)
        )
        return self._data(response)

    async def _post(self, path: str, body: Mapping[str, Any]) -> Any:
        response = await self._http.request(
            "POST", path, json=dict(body), headers=await self._auth_headers(), expected=(200,)
        )
        return self._data(response)

    def _data(self, response: Any) -> Any:
        body = require_mapping(self._http.json(response), panel=self.kind.value, what="reply")
        if body.get("status") is False:
            raise PanelContractViolation(
                str(body.get("message") or "The dashboard refused the request."),
                panel=self.kind.value,
            )
        return body.get("data")

    # -- reading -----------------------------------------------------------

    async def _peers(self) -> list[tuple[Mapping[str, Any], bool]] | None:
        """Every peer in the configuration, with whether it is restricted.

        `None` when the configuration itself is not there - which, for a
        lookup, is the same answer as "no such peer".
        """
        response = await self._http.request(
            "GET",
            "/api/getWireguardConfigurationInfo",
            params={"configurationName": self._configuration},
            headers=await self._auth_headers(),
            expected=(200,),
            allow_status=(404,),
        )
        if response.status_code == 404:
            return None
        data = self._data(response)
        info = require_mapping(data, panel=self.kind.value, what="configuration")
        peers: list[tuple[Mapping[str, Any], bool]] = []
        for key, restricted in (("configurationPeers", False), ("configurationRestrictedPeers", True)):
            rows = info.get(key) or []
            if not isinstance(rows, list):
                raise PanelContractViolation(f"{key} was not a list.", panel=self.kind.value)
            peers.extend(
                (require_mapping(row, panel=self.kind.value, what="peer"), restricted)
                for row in rows
            )
        return peers

    async def _find(self, username: str) -> tuple[Mapping[str, Any], bool] | None:
        for peer, restricted in await self._peers() or []:
            if str(peer.get("name") or "") == username:
                return peer, restricted
        return None

    async def _require(self, ref: PanelAccountRef) -> tuple[Mapping[str, Any], bool]:
        found = await self._find(ref.username)
        if found is None:
            raise AccountNotFound(panel=self.kind.value, username=ref.username)
        return found

    # -- the mandatory surface ----------------------------------------------

    async def health(self) -> PanelHealth:
        started = now_utc()
        try:
            await self._get("/api/handshake")
        except Exception as exc:
            return PanelHealth(is_healthy=False, message=str(exc) or type(exc).__name__)
        return PanelHealth(
            is_healthy=True, latency_ms=(now_utc() - started).total_seconds() * 1000
        )

    async def create_account(self, spec: AccountSpec, *, idempotency_key: str) -> PanelAccount:
        existing = await self._find(spec.username)
        if existing is None:
            body: dict[str, Any] = {
                "bulkAdd": False,
                "name": spec.username,
                # Empty: the dashboard generates the keys and picks the next
                # free address, which is the only way two creates at once
                # cannot both choose the same one.
                "allowed_ips": [],
                "allowed_ips_validation": True,
                "private_key": "",
                "public_key": "",
                "preshared_key": "",
            }
            if self._config.dns:
                body["DNS"] = self._config.dns
            await self._post(f"/api/addPeers/{self._configuration}", body)
            existing = await self._find(spec.username)
            if existing is None:
                raise PanelContractViolation(
                    "The new peer did not appear in the configuration.", panel=self.kind.value
                )
        peer, _ = existing
        peer_id = _peer_id(peer, panel=self.kind.value)
        await self._set_limits(peer, quota=spec.quota, expires_at=spec.expires_at)
        link = await self._share(peer_id, expires_at=spec.expires_at)
        account = await self.get_account(self.ref(spec.username))
        return account if account.subscription_url else _with_link(account, link)

    async def get_account(self, ref: PanelAccountRef) -> PanelAccount:
        peer, restricted = await self._require(ref)
        return self._to_account(peer, restricted=restricted)

    async def find_by_subscription(self, url: str) -> PanelAccount | None:
        wanted = _share_id(url)
        if not wanted:
            return None
        for peer, restricted in await self._peers() or []:
            if wanted in _share_ids(peer):
                return self._to_account(peer, restricted=restricted)
        return None

    async def delete_account(self, ref: PanelAccountRef, *, idempotency_key: str) -> None:
        found = await self._find(ref.username)
        if found is None:
            # Already gone: a retried delete must not raise.
            return
        await self._post(
            f"/api/deletePeers/{self._configuration}",
            {"peers": [_peer_id(found[0], panel=self.kind.value)]},
        )

    async def suspend(self, ref: PanelAccountRef, *, idempotency_key: str) -> PanelAccount:
        peer, restricted = await self._require(ref)
        if not restricted:
            await self._post(
                f"/api/restrictPeers/{self._configuration}",
                {"peers": [_peer_id(peer, panel=self.kind.value)]},
            )
        return await self.get_account(ref)

    async def resume(self, ref: PanelAccountRef, *, idempotency_key: str) -> PanelAccount:
        peer, restricted = await self._require(ref)
        if restricted:
            await self._post(
                f"/api/allowAccessPeers/{self._configuration}",
                {"peers": [_peer_id(peer, panel=self.kind.value)]},
            )
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
        peer, restricted = await self._require(ref)
        current = self._to_account(peer, restricted=restricted)
        expires_at = current.expires_at
        if new_expires_at is not None:
            expires_at = new_expires_at
        elif extend_by is not None:
            expires_at = max(current.expires_at or now_utc(), now_utc()) + extend_by
        quota = new_quota if new_quota is not None else current.usage.quota
        await self._set_limits(peer, quota=quota, expires_at=expires_at)
        if restricted:
            # Renewed is usable again: the job that restricted it has been
            # replaced, but the restriction it applied stays until lifted.
            await self._post(
                f"/api/allowAccessPeers/{self._configuration}",
                {"peers": [_peer_id(peer, panel=self.kind.value)]},
            )
        return await self.get_account(ref)

    # -- capabilities -----------------------------------------------------

    async def reset_traffic(self, ref: PanelAccountRef, *, idempotency_key: str) -> PanelAccount:
        self.require(Capability.RESET_TRAFFIC)
        peer, _ = await self._require(ref)
        await self._post(
            f"/api/resetPeerData/{self._configuration}",
            {"id": _peer_id(peer, panel=self.kind.value), "type": "total"},
        )
        return await self.get_account(ref)

    async def bulk_usage(self, refs: Sequence[PanelAccountRef]) -> Mapping[str, AccountUsage]:
        self.require(Capability.BULK_USAGE)
        wanted = {ref.username for ref in refs}
        if not wanted:
            return {}
        out: dict[str, AccountUsage] = {}
        for peer, _ in await self._peers() or []:
            name = str(peer.get("name") or "")
            if name in wanted:
                out[name] = self._to_usage(peer)
        return out

    async def nodes(self) -> Sequence[NodeInfo]:
        self.require(Capability.NODE_INVENTORY)
        return ()  # pragma: no cover - not declared

    async def subscription(
        self, ref: PanelAccountRef, *, fmt: SubscriptionFormat = SubscriptionFormat.AUTO
    ) -> SubscriptionPayload:
        self.require(Capability.SUBSCRIPTION_URL)
        account = await self.get_account(ref)
        if not account.subscription_url:
            raise PanelContractViolation("The peer has no share link.", panel=self.kind.value)
        return SubscriptionPayload(
            content=account.subscription_url, content_type="text/uri-list", fmt=fmt
        )

    # -- limits as schedule jobs --------------------------------------------

    async def _set_limits(
        self, peer: Mapping[str, Any], *, quota: TrafficQuota, expires_at: datetime | None
    ) -> None:
        """Replace this peer's traffic and date jobs with the ones wanted.

        Replaced rather than added to: two date jobs would restrict the peer
        at the earlier of the two, which after a renewal is the old expiry.
        """
        peer_id = _peer_id(peer, panel=self.kind.value)
        for job in _jobs(peer):
            if job.get("Field") in (TRAFFIC_FIELD, DATE_FIELD):
                await self._post("/api/deletePeerScheduleJob", {"Job": dict(job)})
        if not quota.is_unlimited and quota.total_bytes:
            await self._save_job(peer_id, TRAFFIC_FIELD, f"{quota.total_bytes / GIB:.3f}")
        if expires_at is not None:
            await self._save_job(peer_id, DATE_FIELD, _fmt(expires_at))

    async def _save_job(self, peer_id: str, field: str, value: str) -> None:
        await self._post(
            "/api/savePeerScheduleJob",
            {
                "Job": {
                    "JobID": str(uuid.uuid4()),
                    "Configuration": self._configuration,
                    "Peer": peer_id,
                    "Field": field,
                    # "larger than": restrict once traffic or the date passes it.
                    "Operator": "lgt",
                    "Value": value,
                    "CreationDate": "",
                    "ExpireDate": "",
                    "Action": "restrict",
                }
            },
        )

    async def _share(self, peer_id: str, *, expires_at: datetime | None) -> str | None:
        data = await self._post(
            "/api/sharePeer/create",
            {
                "Configuration": self._configuration,
                "Peer": peer_id,
                "ExpireDate": _fmt(expires_at) if expires_at else "",
            },
        )
        rows = data if isinstance(data, list) else [data]
        for row in rows:
            if isinstance(row, Mapping) and row.get("ShareID"):
                return self._share_url(str(row["ShareID"]))
        return None

    def _share_url(self, share_id: str) -> str:
        return f"{self._config.base_url}/#/share?ShareID={share_id}"

    # -- mapping -----------------------------------------------------------

    def _to_usage(self, peer: Mapping[str, Any]) -> AccountUsage:
        used = _gib(peer.get("total_receive")) + _gib(peer.get("total_sent"))
        limit = next(
            (job.get("Value") for job in _jobs(peer) if job.get("Field") == TRAFFIC_FIELD), None
        )
        return AccountUsage(
            used_bytes=int(used * GIB),
            measured_at=now_utc(),
            quota=TrafficQuota(int(_gib(limit) * GIB) or None),
        )

    def _to_account(self, peer: Mapping[str, Any], *, restricted: bool) -> PanelAccount:
        expires_at = next(
            (_parse(job.get("Value")) for job in _jobs(peer) if job.get("Field") == DATE_FIELD),
            None,
        )
        usage = self._to_usage(peer)
        if restricted:
            if expires_at is not None and expires_at <= now_utc():
                state = AccountState.EXPIRED
            elif usage.quota.total_bytes and usage.used_bytes >= usage.quota.total_bytes:
                state = AccountState.QUOTA_EXHAUSTED
            else:
                state = AccountState.SUSPENDED
        else:
            state = AccountState.ACTIVE
        share_ids = _share_ids(peer)
        return PanelAccount(
            ref=self.ref(str(peer.get("name") or ""), external_id=str(peer.get("id") or "")),
            state=state,
            usage=usage,
            expires_at=expires_at,
            subscription_url=self._share_url(share_ids[0]) if share_ids else None,
        )


def _peer_id(peer: Mapping[str, Any], *, panel: str) -> str:
    peer_id = peer.get("id")
    if not isinstance(peer_id, str) or not peer_id:
        raise PanelContractViolation("A peer had no id.", panel=panel)
    return peer_id


def _jobs(peer: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    jobs = peer.get("jobs") or []
    return [job for job in jobs if isinstance(job, Mapping)] if isinstance(jobs, list) else []


def _share_ids(peer: Mapping[str, Any]) -> list[str]:
    links = peer.get("ShareLink") or []
    if not isinstance(links, list):
        return []
    return [str(link["ShareID"]) for link in links if isinstance(link, Mapping) and link.get("ShareID")]


def _share_id(url: str) -> str | None:
    """The ShareID in a share link, which sits after the `#`."""
    parsed = urlparse(url.strip())
    query = parsed.fragment.partition("?")[2] or parsed.query
    values = parse_qs(query).get("ShareID")
    return values[0] if values else None


def _with_link(account: PanelAccount, link: str | None) -> PanelAccount:
    return PanelAccount(
        ref=account.ref,
        state=account.state,
        usage=account.usage,
        expires_at=account.expires_at,
        subscription_url=link,
        links=account.links,
    )


def _gib(value: Any) -> float:
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        return 0.0


def _fmt(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(DATE_FORMAT)


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.strptime(value.strip(), DATE_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


__all__ = ["WgDashboardAdapter"]
