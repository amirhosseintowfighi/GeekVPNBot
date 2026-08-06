"""Template service — CRUD for canned replies."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from geekvpn.application.support.ports import Clock, IdGenerator, TemplateRepository
from geekvpn.domain.support.enums import TicketCategory
from geekvpn.domain.support.template import Template


@dataclass(frozen=True, slots=True)
class TemplateView:
    template_id: str
    title_fa: str
    body_fa: str
    categories: frozenset[TicketCategory]
    is_active: bool
    use_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_template(cls, t: Template) -> TemplateView:
        return cls(
            template_id=t.id,
            title_fa=t.title_fa,
            body_fa=t.body_fa,
            categories=t.categories,
            is_active=t.is_active,
            use_count=t.use_count,
            created_at=t.created_at,
            updated_at=t.updated_at,
        )


class TemplateService:
    def __init__(
        self,
        *,
        templates: TemplateRepository,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._templates = templates
        self._clock = clock
        self._ids = ids

    def create(
        self,
        *,
        title_fa: str,
        body_fa: str,
        categories: Sequence[TicketCategory] | None = None,
    ) -> TemplateView:
        now = self._clock.now()
        template_id = self._ids.new_id()
        tmpl = Template.create(
            template_id,
            title_fa=title_fa,
            body_fa=body_fa,
            categories=categories,
            now=now,
        )
        self._templates.save(tmpl)
        return TemplateView.from_template(tmpl)

    def update(
        self,
        template_id: str,
        *,
        title_fa: str | None = None,
        body_fa: str | None = None,
        categories: Sequence[TicketCategory] | None = None,
    ) -> TemplateView:
        now = self._clock.now()
        tmpl = self._templates.get(template_id)
        tmpl.update(title_fa=title_fa, body_fa=body_fa, categories=categories, now=now)
        self._templates.save(tmpl)
        return TemplateView.from_template(tmpl)

    def deactivate(self, template_id: str) -> TemplateView:
        now = self._clock.now()
        tmpl = self._templates.get(template_id)
        tmpl.deactivate(now)
        self._templates.save(tmpl)
        return TemplateView.from_template(tmpl)

    def activate(self, template_id: str) -> TemplateView:
        now = self._clock.now()
        tmpl = self._templates.get(template_id)
        tmpl.activate(now)
        self._templates.save(tmpl)
        return TemplateView.from_template(tmpl)

    def delete(self, template_id: str) -> None:
        self._templates.delete(template_id)

    def list_active(self, *, category: TicketCategory | None = None) -> list[TemplateView]:
        return [
            TemplateView.from_template(t) for t in self._templates.list_active(category=category)
        ]

    def get(self, template_id: str) -> TemplateView:
        return TemplateView.from_template(self._templates.get(template_id))


__all__ = ["TemplateService", "TemplateView"]
