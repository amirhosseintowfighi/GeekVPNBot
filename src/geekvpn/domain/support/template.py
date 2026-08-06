"""Reply templates — canned answers the support team can insert in one tap.

A template is the answer to a question the team has answered a hundred times.
Storing them in the database rather than in code means a support lead can add
or update them without a deployment.

Templates are keyed by category so the admin panel can offer a filtered list
when an agent is working a payment ticket.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from geekvpn.domain.base.entity import AggregateRoot
from geekvpn.domain.base.errors import ValidationError
from geekvpn.domain.support.enums import TicketCategory

MIN_TITLE: int = 3
MIN_BODY: int = 10


class Template(AggregateRoot[str]):
    """A pre-written reply an agent can use to respond quickly.

    The body may contain ``{{placeholder}}`` tokens that the admin panel
    replaces before inserting into the reply composer. This is intentionally
    a simple string convention rather than a templating engine — the support
    team writes in Persian, not Jinja.
    """

    __slots__ = (
        "body_fa",
        "categories",
        "created_at",
        "is_active",
        "title_fa",
        "updated_at",
        "use_count",
    )

    def __init__(
        self,
        template_id: str,
        *,
        title_fa: str,
        body_fa: str,
        categories: frozenset[TicketCategory],
        is_active: bool = True,
        created_at: datetime,
        updated_at: datetime,
        use_count: int = 0,
    ) -> None:
        super().__init__(template_id)
        self.title_fa = title_fa
        self.body_fa = body_fa
        self.categories = categories
        self.is_active = is_active
        self.created_at = created_at
        self.updated_at = updated_at
        self.use_count = use_count

    # -- factories ---------------------------------------------------------

    @classmethod
    def create(
        cls,
        template_id: str,
        *,
        title_fa: str,
        body_fa: str,
        categories: Sequence[TicketCategory] | None = None,
        now: datetime,
    ) -> Template:
        cls._validate(title_fa=title_fa, body_fa=body_fa)
        return cls(
            template_id,
            title_fa=title_fa,
            body_fa=body_fa,
            categories=frozenset(categories or []),
            is_active=True,
            created_at=now,
            updated_at=now,
        )

    # -- mutations ---------------------------------------------------------

    def update(
        self,
        *,
        title_fa: str | None = None,
        body_fa: str | None = None,
        categories: Sequence[TicketCategory] | None = None,
        now: datetime,
    ) -> None:
        new_title = title_fa if title_fa is not None else self.title_fa
        new_body = body_fa if body_fa is not None else self.body_fa
        self._validate(title_fa=new_title, body_fa=new_body)
        self.title_fa = new_title
        self.body_fa = new_body
        if categories is not None:
            self.categories = frozenset(categories)
        self.updated_at = now

    def activate(self, now: datetime) -> None:
        self.is_active = True
        self.updated_at = now

    def deactivate(self, now: datetime) -> None:
        self.is_active = False
        self.updated_at = now

    def record_use(self) -> None:
        """Increment the use counter so popular templates bubble up."""
        self.use_count += 1

    def applies_to(self, category: TicketCategory) -> bool:
        """A template with no categories applies to every ticket."""
        return not self.categories or category in self.categories

    # -- private -----------------------------------------------------------

    @staticmethod
    def _validate(*, title_fa: str, body_fa: str) -> None:
        if len(title_fa.strip()) < MIN_TITLE:
            raise ValidationError(
                f"Template title must be at least {MIN_TITLE} characters.",
                field="title_fa",
            )
        if len(body_fa.strip()) < MIN_BODY:
            raise ValidationError(
                f"Template body must be at least {MIN_BODY} characters.",
                field="body_fa",
            )


__all__ = ["MIN_BODY", "MIN_TITLE", "Template"]
