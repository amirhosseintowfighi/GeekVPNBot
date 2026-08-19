"""The support desk for the admin panel: the queue, one ticket, and replies.

Decisions worth knowing before changing anything here
-----------------------------------------------------
* **The queue is ordered by waiting time, not by priority.** That choice lives
  in ``SyncTicketRepository.all_open``; this router does not re-sort it. If it
  sorted by priority a steady trickle of urgent tickets would starve every
  normal one forever.
* **The total is a real count.** ``count_open`` runs the same filters as the
  page query, so the pager cannot tell an agent looking at 25 tickets that
  there are exactly 25 when there are 300.
* **Agents see internal notes, customers never do.** Every read here passes
  ``include_internal=True``; the customer-facing Mini App route must not.
* **Marking a ticket read is a POST, not a side effect of the GET.** Opening a
  ticket to look at it should not silently rewrite the customer's unread badge
  when a proxy or a preloader is the one doing the opening.
* Replies and notes are mutations that must not replay, so they require an
  ``Idempotency-Key``. Reading requires none.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import ConfigDict, Field

from geekvpn.application.support.search_service import SearchQuery
from geekvpn.application.support.ticket_service import NoteRequest, ReplyRequest
from geekvpn.domain.identity.permissions import Permission
from geekvpn.domain.support.enums import TicketCategory, TicketPriority, TicketState
from geekvpn.infrastructure.di.sync_scope import SyncScope
from geekvpn.presentation.api.admin_common import (
    ADMIN_PAGE_SIZE,
    ActorId,
    IdempotencyKey,
    PageQuery,
    claim_idempotency,
    mutate_scope,
    read_scope,
)
from geekvpn.presentation.api.base_schema import ApiModel
from geekvpn.presentation.api.dependencies import ContainerDep
from geekvpn.presentation.api.security import CurrentAdmin, requires

router = APIRouter(prefix="/admin/tickets", tags=["support"])
templates_router = APIRouter(prefix="/admin/reply-templates", tags=["support"])


# -- request bodies ---------------------------------------------------------


class ReplyBody(ApiModel):
    model_config = ConfigDict(extra="forbid")

    bodyFa: str = Field(min_length=1, max_length=4_000)
    templateId: str | None = Field(
        default=None,
        description="Recorded when the reply came from a canned template, for its use count.",
    )


class NoteBody(ApiModel):
    model_config = ConfigDict(extra="forbid")

    bodyFa: str = Field(min_length=1, max_length=4_000)


class PriorityBody(ApiModel):
    model_config = ConfigDict(extra="forbid")

    priority: TicketPriority


class CategoryBody(ApiModel):
    model_config = ConfigDict(extra="forbid")

    category: TicketCategory


class AssignBody(ApiModel):
    model_config = ConfigDict(extra="forbid")

    assigneeId: int | None = Field(
        default=None, description="Null unassigns the ticket and returns it to the queue."
    )


class TemplateCreateBody(ApiModel):
    model_config = ConfigDict(extra="forbid")

    titleFa: str = Field(min_length=2, max_length=120)
    bodyFa: str = Field(min_length=2, max_length=4_000)
    categories: list[TicketCategory] = Field(default_factory=list)


class TemplateUpdateBody(ApiModel):
    model_config = ConfigDict(extra="forbid")

    titleFa: str | None = Field(default=None, min_length=2, max_length=120)
    bodyFa: str | None = Field(default=None, min_length=2, max_length=4_000)
    categories: list[TicketCategory] | None = None


# -- serialisation ----------------------------------------------------------


def _summary_dict(summary: Any) -> dict[str, Any]:
    return {
        "ticketId": summary.ticket_id,
        "userId": summary.user_id,
        "reference": summary.reference,
        "category": summary.category.value,
        "priority": summary.priority.value,
        "state": summary.state.value,
        "subjectFa": summary.subject_fa,
        "assigneeId": summary.assignee_id,
        "createdAt": summary.created_at.isoformat(),
        "updatedAt": summary.updated_at.isoformat(),
        "messageCount": summary.message_count,
        "unreadForAgent": summary.unread_for_agent,
        "unreadForCustomer": summary.unread_for_customer,
        "waitingMinutes": summary.waiting_minutes,
    }


def _message_dict(message: Any) -> dict[str, Any]:
    return {
        "messageId": message.message_id,
        "ticketId": message.ticket_id,
        "kind": message.kind.value,
        "bodyFa": message.body_fa,
        "authorId": message.author_id,
        "createdAt": message.created_at.isoformat(),
        "attachmentCount": message.attachment_count,
        "templateId": message.template_id,
        "isRead": message.is_read,
    }


def _template_dict(template: Any) -> dict[str, Any]:
    return {
        "templateId": template.template_id,
        "titleFa": template.title_fa,
        "bodyFa": template.body_fa,
        "categories": sorted(c.value for c in template.categories),
        "isActive": template.is_active,
        "useCount": template.use_count,
        "createdAt": template.created_at.isoformat(),
        "updatedAt": template.updated_at.isoformat(),
    }


# -- the queue --------------------------------------------------------------


@router.get(
    "",
    summary="The open-ticket queue, longest wait first",
    dependencies=[Depends(requires(Permission.TICKETS_READ))],
)
async def ticket_queue(
    container: ContainerDep,
    admin: CurrentAdmin,
    category: TicketCategory | None = None,
    priority: TicketPriority | None = None,
    assigneeId: int | None = None,
    page: PageQuery = 1,
) -> dict[str, Any]:
    offset = (page - 1) * ADMIN_PAGE_SIZE

    def work(scope: SyncScope) -> dict[str, Any]:
        summaries = scope.support.queue(
            category=category,
            priority=priority,
            assignee_id=assigneeId,
            limit=ADMIN_PAGE_SIZE,
            offset=offset,
        )
        return {
            "items": [_summary_dict(s) for s in summaries],
            "page": page,
            "pageSize": ADMIN_PAGE_SIZE,
            "total": scope.tickets.count_open(
                category=category, priority=priority, assignee_id=assigneeId
            ),
        }

    return await read_scope(container, work)


@router.get(
    "/search",
    summary="Search tickets by subject and body",
    dependencies=[Depends(requires(Permission.TICKETS_READ))],
)
async def search_tickets(
    container: ContainerDep,
    admin: CurrentAdmin,
    q: Annotated[str, Query(min_length=2, max_length=120)],
    state: TicketState | None = None,
    userId: int | None = None,
    page: PageQuery = 1,
) -> dict[str, Any]:
    query = SearchQuery(
        query=q,
        user_id=userId,
        state=state,
        limit=ADMIN_PAGE_SIZE,
        offset=(page - 1) * ADMIN_PAGE_SIZE,
    )

    def work(scope: SyncScope) -> dict[str, Any]:
        result = scope.support_search.search(query)
        return {
            "items": [_summary_dict(s) for s in result.summaries],
            "page": page,
            "pageSize": ADMIN_PAGE_SIZE,
            "total": result.total,
            "query": result.query,
        }

    return await read_scope(container, work)


@router.get(
    "/{ticket_id}",
    summary="One ticket",
    dependencies=[Depends(requires(Permission.TICKETS_READ))],
)
async def get_ticket(
    ticket_id: str, container: ContainerDep, admin: CurrentAdmin
) -> dict[str, Any]:
    def work(scope: SyncScope) -> dict[str, Any]:
        return _summary_dict(scope.support.get_ticket(ticket_id))

    return await read_scope(container, work)


@router.get(
    "/{ticket_id}/messages",
    summary="Full history, including internal notes",
    dependencies=[Depends(requires(Permission.TICKETS_READ))],
)
async def get_messages(
    ticket_id: str, container: ContainerDep, admin: CurrentAdmin
) -> dict[str, Any]:
    def work(scope: SyncScope) -> dict[str, Any]:
        messages = scope.support.get_messages(ticket_id, include_internal=True)
        return {"items": [_message_dict(m) for m in messages]}

    return await read_scope(container, work)


# -- acting on a ticket -----------------------------------------------------


@router.post(
    "/{ticket_id}/mark-read",
    status_code=status.HTTP_200_OK,
    summary="Mark the customer's messages as read by an agent",
    dependencies=[Depends(requires(Permission.TICKETS_READ))],
)
async def mark_read(ticket_id: str, container: ContainerDep, admin: CurrentAdmin) -> dict[str, Any]:
    def work(scope: SyncScope) -> dict[str, Any]:
        return {"markedRead": scope.support.mark_read(ticket_id, viewer_is_agent=True)}

    return await mutate_scope(container, work)


@router.post(
    "/{ticket_id}/reply",
    status_code=status.HTTP_201_CREATED,
    summary="Reply to the customer",
    dependencies=[Depends(requires(Permission.TICKETS_REPLY))],
)
async def reply(
    ticket_id: str,
    payload: ReplyBody,
    idempotency_key: IdempotencyKey,
    container: ContainerDep,
    actor: ActorId,
) -> dict[str, Any]:
    await claim_idempotency(container, idempotency_key, scope_label=f"ticket.reply:{ticket_id}")
    request = ReplyRequest(
        ticket_id=ticket_id,
        body_fa=payload.bodyFa,
        author_id=actor,
        template_id=payload.templateId,
    )

    def work(scope: SyncScope) -> dict[str, Any]:
        return _message_dict(scope.support.agent_reply(request))

    return await mutate_scope(container, work)


@router.post(
    "/{ticket_id}/note",
    status_code=status.HTTP_201_CREATED,
    summary="Add an internal note the customer never sees",
    dependencies=[Depends(requires(Permission.TICKETS_REPLY))],
)
async def add_note(
    ticket_id: str,
    payload: NoteBody,
    idempotency_key: IdempotencyKey,
    container: ContainerDep,
    actor: ActorId,
) -> dict[str, Any]:
    await claim_idempotency(container, idempotency_key, scope_label=f"ticket.note:{ticket_id}")
    request = NoteRequest(ticket_id=ticket_id, body_fa=payload.bodyFa, author_id=actor)

    def work(scope: SyncScope) -> dict[str, Any]:
        return _message_dict(scope.support.add_note(request))

    return await mutate_scope(container, work)


@router.post(
    "/{ticket_id}/close",
    status_code=status.HTTP_200_OK,
    summary="Close a ticket",
    dependencies=[Depends(requires(Permission.TICKETS_REPLY))],
)
async def close_ticket(
    ticket_id: str,
    idempotency_key: IdempotencyKey,
    container: ContainerDep,
    actor: ActorId,
) -> dict[str, Any]:
    await claim_idempotency(container, idempotency_key, scope_label=f"ticket.close:{ticket_id}")

    def work(scope: SyncScope) -> dict[str, Any]:
        return _summary_dict(
            scope.support.close_ticket(ticket_id, actor_id=actor, closed_by_agent=True)
        )

    return await mutate_scope(container, work)


@router.post(
    "/{ticket_id}/priority",
    status_code=status.HTTP_200_OK,
    summary="Change a ticket's priority",
    dependencies=[Depends(requires(Permission.TICKETS_REPLY))],
)
async def change_priority(
    ticket_id: str,
    payload: PriorityBody,
    container: ContainerDep,
    actor: ActorId,
) -> dict[str, Any]:
    def work(scope: SyncScope) -> dict[str, Any]:
        return _summary_dict(
            scope.support.change_priority(ticket_id, payload.priority, actor_id=actor)
        )

    return await mutate_scope(container, work)


@router.post(
    "/{ticket_id}/category",
    status_code=status.HTTP_200_OK,
    summary="Re-file a ticket under another category",
    dependencies=[Depends(requires(Permission.TICKETS_REPLY))],
)
async def change_category(
    ticket_id: str,
    payload: CategoryBody,
    container: ContainerDep,
    actor: ActorId,
) -> dict[str, Any]:
    def work(scope: SyncScope) -> dict[str, Any]:
        return _summary_dict(
            scope.support.change_category(ticket_id, payload.category, actor_id=actor)
        )

    return await mutate_scope(container, work)


@router.post(
    "/{ticket_id}/assign",
    status_code=status.HTTP_200_OK,
    summary="Assign a ticket to an agent, or return it to the queue",
    dependencies=[Depends(requires(Permission.TICKETS_ASSIGN))],
)
async def assign_ticket(
    ticket_id: str,
    payload: AssignBody,
    container: ContainerDep,
    actor: ActorId,
) -> dict[str, Any]:
    def work(scope: SyncScope) -> dict[str, Any]:
        return _summary_dict(
            scope.support.assign_ticket(ticket_id, payload.assigneeId, actor_id=actor)
        )

    return await mutate_scope(container, work)


# -- canned replies ---------------------------------------------------------


@templates_router.get(
    "",
    summary="Active reply templates",
    dependencies=[Depends(requires(Permission.TICKETS_READ))],
)
async def list_templates(
    container: ContainerDep,
    admin: CurrentAdmin,
    category: TicketCategory | None = None,
) -> dict[str, Any]:
    def work(scope: SyncScope) -> dict[str, Any]:
        views = scope.support_templates.list_active(category=category)
        return {"items": [_template_dict(v) for v in views]}

    return await read_scope(container, work)


@templates_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a reply template",
    dependencies=[Depends(requires(Permission.TICKETS_REPLY))],
)
async def create_template(
    payload: TemplateCreateBody,
    idempotency_key: IdempotencyKey,
    container: ContainerDep,
    admin: CurrentAdmin,
) -> dict[str, Any]:
    await claim_idempotency(container, idempotency_key, scope_label="template.create")

    def work(scope: SyncScope) -> dict[str, Any]:
        return _template_dict(
            scope.support_templates.create(
                title_fa=payload.titleFa,
                body_fa=payload.bodyFa,
                categories=payload.categories or None,
            )
        )

    return await mutate_scope(container, work)


@templates_router.patch(
    "/{template_id}",
    status_code=status.HTTP_200_OK,
    summary="Edit a reply template",
    dependencies=[Depends(requires(Permission.TICKETS_REPLY))],
)
async def update_template(
    template_id: str,
    payload: TemplateUpdateBody,
    container: ContainerDep,
    admin: CurrentAdmin,
) -> dict[str, Any]:
    def work(scope: SyncScope) -> dict[str, Any]:
        return _template_dict(
            scope.support_templates.update(
                template_id,
                title_fa=payload.titleFa,
                body_fa=payload.bodyFa,
                categories=payload.categories,
            )
        )

    return await mutate_scope(container, work)


@templates_router.post(
    "/{template_id}/activate",
    status_code=status.HTTP_200_OK,
    summary="Bring a template back into use",
    dependencies=[Depends(requires(Permission.TICKETS_REPLY))],
)
async def activate_template(
    template_id: str, container: ContainerDep, admin: CurrentAdmin
) -> dict[str, Any]:
    def work(scope: SyncScope) -> dict[str, Any]:
        return _template_dict(scope.support_templates.activate(template_id))

    return await mutate_scope(container, work)


@templates_router.post(
    "/{template_id}/deactivate",
    status_code=status.HTTP_200_OK,
    summary="Retire a template without deleting its history",
    dependencies=[Depends(requires(Permission.TICKETS_REPLY))],
)
async def deactivate_template(
    template_id: str, container: ContainerDep, admin: CurrentAdmin
) -> dict[str, Any]:
    def work(scope: SyncScope) -> dict[str, Any]:
        return _template_dict(scope.support_templates.deactivate(template_id))

    return await mutate_scope(container, work)


@templates_router.delete(
    "/{template_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a reply template",
    dependencies=[Depends(requires(Permission.TICKETS_REPLY))],
)
async def delete_template(
    template_id: str, container: ContainerDep, admin: CurrentAdmin
) -> dict[str, Any]:
    def work(scope: SyncScope) -> dict[str, Any]:
        scope.support_templates.delete(template_id)
        return {"messageFa": "قالب پاسخ حذف شد."}

    return await mutate_scope(container, work)


__all__ = ["router", "templates_router"]
