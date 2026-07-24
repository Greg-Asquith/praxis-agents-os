"""Provider-neutral integration event processing behavior."""

import importlib
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from models.integrations import IntegrationEvent
from services.integrations.plugin import ProcessedIntegrationEvent
from tests.factories import build_integration_event, build_integration_webhook

process_event_module = importlib.import_module("services.integrations.events.process_event")


async def test_process_event_uses_provider_contribution_once(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = discovery_connection["connection"]
    calls: list[str] = []

    async def process(_db, _webhook, event):
        calls.append(str(event.id))
        return ProcessedIntegrationEvent(payload={"normalized": True})

    monkeypatch.setitem(
        process_event_module.PROVIDER_PLUGINS,
        connection.provider_key,
        SimpleNamespace(event_definition=SimpleNamespace(process=process)),
    )
    webhook = build_integration_webhook(connection=connection)
    db_session.add(webhook)
    await db_session.flush()
    event = build_integration_event(connection=connection, webhook=webhook)
    db_session.add(event)
    await db_session.flush()

    await process_event_module.process_event(db_session, event_id=event.id)
    await process_event_module.process_event(db_session, event_id=event.id)

    persisted = await db_session.get(IntegrationEvent, event.id)
    assert persisted is not None
    assert persisted.status == "processed"
    assert persisted.payload == {"normalized": True}
    assert persisted.processed_at is not None
    assert calls == [str(event.id)]
