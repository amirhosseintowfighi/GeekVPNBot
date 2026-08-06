"""Runtime settings: declaration, coercion, audit."""

from __future__ import annotations

import uuid

import pytest

from geekvpn.application.platform.settings_service import (
    MAINTENANCE_MODE,
    SETTING_REGISTRY,
    SUPPORT_TELEGRAM_HANDLE,
    SettingsService,
)
from geekvpn.domain.audit.entry import AuditAction
from geekvpn.domain.base.errors import NotFoundError, ValidationError
from tests.fakes import InMemorySettingsStore, RecordingAudit

ACTOR = uuid.uuid4()


@pytest.fixture
def service_parts():
    store = InMemorySettingsStore()
    audit = RecordingAudit()
    return SettingsService(store=store, audit=audit), store, audit


async def test_an_unset_setting_returns_its_declared_default(service_parts):
    service, _, _ = service_parts
    assert await service.get(MAINTENANCE_MODE) is False


async def test_a_written_value_is_read_back(service_parts):
    service, _, _ = service_parts
    await service.set(MAINTENANCE_MODE.key, True, actor_id=ACTOR)
    assert await service.get(MAINTENANCE_MODE) is True


async def test_writing_an_undeclared_key_is_refused(service_parts):
    """Stops the settings table filling with typos that nothing ever reads."""
    service, _, _ = service_parts
    with pytest.raises(NotFoundError):
        await service.set("platform.maintenence_mode", True, actor_id=ACTOR)


async def test_a_wrongly_typed_value_is_refused_at_write_time(service_parts):
    service, _, _ = service_parts
    with pytest.raises(ValidationError):
        await service.set(SUPPORT_TELEGRAM_HANDLE.key, 42, actor_id=ACTOR)


async def test_boolean_strings_are_coerced(service_parts):
    service, _, _ = service_parts
    await service.set(MAINTENANCE_MODE.key, "yes", actor_id=ACTOR)
    assert await service.get(MAINTENANCE_MODE) is True


async def test_a_corrupt_stored_value_falls_back_to_the_default(service_parts):
    """A settings problem must never take the platform down."""
    service, store, _ = service_parts
    await store.set(MAINTENANCE_MODE.key, {"unexpected": "shape"})
    assert await service.get(MAINTENANCE_MODE) is False


async def test_every_change_is_audited_with_before_and_after(service_parts):
    service, _, audit = service_parts
    await service.set(MAINTENANCE_MODE.key, True, actor_id=ACTOR)

    assert AuditAction.SETTING_CHANGED in audit.actions()
    entry = audit.entries[-1]
    assert entry["target_id"] == MAINTENANCE_MODE.key
    assert entry["metadata"]["new"] is True


async def test_listing_covers_every_declared_setting(service_parts):
    service, _, _ = service_parts
    records = await service.list_all()
    assert {record.key for record in records} == set(SETTING_REGISTRY)
