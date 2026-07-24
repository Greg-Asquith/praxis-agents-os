# apps/api/services/integrations/events/process_event.py

"""Idempotently process one authenticated integration event."""

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationConnectionError
from core.settings import settings
from models.integrations import IntegrationEvent, IntegrationWebhook
from services.integrations.events.domain import TERMINAL_EVENT_STATUSES
from services.integrations.plugin import PROVIDER_PLUGINS


async def process_event(db: AsyncSession, *, event_id: UUID) -> None:
    """Run the provider processor once while holding the durable event lock."""
    event = await db.scalar(
        select(IntegrationEvent).where(IntegrationEvent.id == event_id).with_for_update()
    )
    if event is None or event.status in TERMINAL_EVENT_STATUSES:
        return
    webhook = await db.scalar(
        select(IntegrationWebhook)
        .where(IntegrationWebhook.id == event.webhook_id)
        .with_for_update()
    )
    if webhook is None or webhook.status != "active":
        _discard(event, "webhook_unavailable")
        return
    plugin = PROVIDER_PLUGINS.get(event.provider_key)
    if plugin is None or plugin.event_definition is None:
        raise RuntimeError("Integration event provider is not available")
    try:
        result = await plugin.event_definition.process(db, webhook, event)
    except IntegrationConnectionError:
        _discard(event, "connection_unavailable")
        return
    if result.discard_reason is not None:
        _discard(event, result.discard_reason)
        return
    event.payload = _bounded_payload(result.payload)
    event.status = "processed"
    event.processed_at = datetime.now(UTC)
    event.discard_reason = None
    await db.flush()


def _discard(event: IntegrationEvent, reason: str) -> None:
    event.status = "discarded"
    event.processed_at = datetime.now(UTC)
    event.discard_reason = reason[:128]


def _bounded_payload(payload: dict[str, object] | None) -> dict[str, object] | None:
    if payload is None:
        return None
    encoded = json.dumps(payload, separators=(",", ":"), default=str).encode()
    if len(encoded) <= settings.INTEGRATIONS_EVENT_PAYLOAD_MAX_BYTES:
        return payload
    return {"payload_omitted": True, "encoded_bytes": len(encoded)}
