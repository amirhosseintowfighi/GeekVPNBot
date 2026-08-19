"""Node (panel) administration.

Without this router the platform cannot sell anything: provisioning picks a node
from the database, and until an operator can add one there is nothing to pick.

Two rules shape every response here:

* The panel password goes **in** and never comes back out. Responses carry
  ``has_password`` so an operator can tell a configured node from an unconfigured
  one without the value ever being serialised.
* ``test-connection`` performs a real authenticated call through
  :meth:`PanelProvider.for_node`, because a check that only reaches ``base_url``
  proves the host is up and proves nothing about the credentials - which is the
  half that actually breaks.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ConfigDict, Field

from geekvpn.application.provisioning.ports import NodeAdminRecord
from geekvpn.domain.identity.permissions import Permission
from geekvpn.domain.panels.enums import PanelKind
from geekvpn.domain.panels.errors import PanelError
from geekvpn.domain.provisioning.enums import NodeState
from geekvpn.presentation.api.base_schema import ApiModel
from geekvpn.presentation.api.security import ScopeDep, requires

router = APIRouter(prefix="/admin/panels", tags=["administration"])


class NodeResponse(ApiModel):
    """What an operator is allowed to see. Note the absent password."""

    id: str
    name_fa: str
    panel_kind: PanelKind
    state: NodeState
    base_url: str
    username: str
    has_password: bool
    verify_tls: bool
    timeout_seconds: float
    capacity: int
    account_count: int
    accepting_new: bool
    country_code: str | None
    sort_order: int
    last_check_at: datetime | None
    last_error: str | None

    @classmethod
    def of(cls, record: NodeAdminRecord) -> NodeResponse:
        return cls(
            id=record.id,
            name_fa=record.name_fa,
            panel_kind=record.panel_kind,
            state=record.state,
            base_url=record.base_url,
            username=record.username,
            has_password=record.has_password,
            verify_tls=record.verify_tls,
            timeout_seconds=record.timeout_seconds,
            capacity=record.capacity,
            account_count=record.account_count,
            accepting_new=record.accepting_new,
            country_code=record.country_code,
            sort_order=record.sort_order,
            last_check_at=record.last_check_at,
            last_error=record.last_error,
        )


class CreateNodeRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name_fa: str = Field(min_length=1, max_length=128)
    panel_kind: PanelKind
    base_url: str = Field(min_length=8, max_length=256)
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    #: 0 means "no declared ceiling", matching `NodeRecord.has_room`.
    capacity: int = Field(default=0, ge=0)
    verify_tls: bool = True
    timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    sort_order: int = 0
    config: dict[str, object] = Field(default_factory=dict)


class UpdateNodeRequest(ApiModel):
    """Every field optional; omitted fields are left untouched.

    ``password`` omitted means "keep the stored one", which is what lets the
    admin panel save a node it was never shown the password for.
    """

    model_config = ConfigDict(extra="forbid")

    name_fa: str | None = Field(default=None, min_length=1, max_length=128)
    base_url: str | None = Field(default=None, min_length=8, max_length=256)
    username: str | None = Field(default=None, min_length=1, max_length=128)
    password: str | None = Field(default=None, min_length=1, max_length=256)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    capacity: int | None = Field(default=None, ge=0)
    verify_tls: bool | None = None
    timeout_seconds: float | None = Field(default=None, gt=0, le=120)
    sort_order: int | None = None
    state: NodeState | None = None
    accepting_new: bool | None = None


class TestConnectionResponse(ApiModel):
    ok: bool
    latency_ms: float | None = None
    version: str | None = None
    message: str | None = None


@router.get(
    "",
    response_model=list[NodeResponse],
    summary="List every node",
    dependencies=[Depends(requires(Permission.PANELS_READ))],
)
async def list_nodes(scope: ScopeDep) -> list[NodeResponse]:
    return [NodeResponse.of(record) for record in await scope.nodes.list_all()]


@router.get(
    "/{node_id}",
    response_model=NodeResponse,
    summary="One node",
    dependencies=[Depends(requires(Permission.PANELS_READ))],
)
async def get_node(node_id: str, scope: ScopeDep) -> NodeResponse:
    record = await scope.nodes.get_for_admin(node_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Node not found.")
    return NodeResponse.of(record)


@router.post(
    "",
    response_model=NodeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a node",
    dependencies=[Depends(requires(Permission.PANELS_WRITE))],
)
async def create_node(payload: CreateNodeRequest, scope: ScopeDep) -> NodeResponse:
    if await scope.nodes.get_for_admin(payload.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="A node with this id exists.")
    record = await scope.nodes.create(
        node_id=payload.id,
        name_fa=payload.name_fa,
        panel_kind=payload.panel_kind,
        base_url=payload.base_url,
        username=payload.username,
        password=payload.password,
        country_code=payload.country_code,
        capacity=payload.capacity,
        verify_tls=payload.verify_tls,
        timeout_seconds=payload.timeout_seconds,
        sort_order=payload.sort_order,
        config=payload.config,
    )
    return NodeResponse.of(record)


@router.patch(
    "/{node_id}",
    response_model=NodeResponse,
    summary="Edit a node",
    dependencies=[Depends(requires(Permission.PANELS_WRITE))],
)
async def update_node(node_id: str, payload: UpdateNodeRequest, scope: ScopeDep) -> NodeResponse:
    changes = payload.model_dump(exclude_unset=True)
    if "state" in changes and changes["state"] is not None:
        changes["state"] = NodeState(changes["state"]).value
    record = await scope.nodes.update(node_id, **changes)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Node not found.")
    return NodeResponse.of(record)


@router.delete(
    "/{node_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a node",
    dependencies=[Depends(requires(Permission.PANELS_WRITE))],
)
async def delete_node(node_id: str, scope: ScopeDep) -> None:
    if not await scope.nodes.delete(node_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Node not found.")


@router.post(
    "/{node_id}/test-connection",
    response_model=TestConnectionResponse,
    summary="Log in to the panel and report what happened",
    dependencies=[Depends(requires(Permission.PANELS_WRITE))],
)
async def test_connection(node_id: str, scope: ScopeDep) -> TestConnectionResponse:
    """Build a real adapter and call ``health()``, which authenticates first.

    A failure is a 200 carrying ``ok: false``, not an HTTP error: the request to
    test the node succeeded, and the operator needs the panel's own message to
    act on. The outcome is stored so the list view shows it without re-testing.
    """
    record = await scope.nodes.get(node_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Node not found.")

    now = datetime.now(UTC)
    try:
        adapter = await scope.panel_provider.for_node(record)
        health = await adapter.health()
    except PanelError as exc:
        await scope.nodes.record_check(node_id, at=now, error=str(exc))
        return TestConnectionResponse(ok=False, message=str(exc))

    await scope.nodes.record_check(
        node_id, at=now, error=None if health.is_healthy else health.message
    )
    return TestConnectionResponse(
        ok=health.is_healthy,
        latency_ms=health.latency_ms,
        version=health.version,
        message=health.message,
    )
