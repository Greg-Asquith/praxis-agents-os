# apps/api/services/integrations/events/receive_event.py

"""Verify and durably enqueue one inbound integration event."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.integrations import IntegrationConnection, IntegrationEvent, IntegrationWebhook
from services.integrations.events.domain import PROCESS_EVENT_KIND, WebhookVerificationError
from services.integrations.plugin import (
    PROVIDER_PLUGINS,
    IntegrationEventRequest,
)


async def receive_event(
    db: AsyncSession,
    *,
    provider_key: str,
    receipt_id: str,
    request: IntegrationEventRequest,
) -> bool:
    """Authenticate, insert, and enqueue; return whether a new event was created."""
    from services.jobs.enqueue_job import enqueue_job

    plugin = PROVIDER_PLUGINS.get(provider_key)
    if plugin is None or plugin.event_definition is None:
        raise WebhookVerificationError("provider_unavailable")
    webhook_row = (
        await db.execute(
            select(IntegrationWebhook, IntegrationConnection.owner_workspace_id)
            .join(
                IntegrationConnection,
                IntegrationConnection.id == IntegrationWebhook.connection_id,
            )
            .where(
                IntegrationWebhook.provider_key == provider_key,
                IntegrationWebhook.receipt_id == receipt_id,
                IntegrationWebhook.status == "active",
                IntegrationConnection.deleted.is_(False),
            )
        )
    ).one_or_none()
    if webhook_row is None:
        raise WebhookVerificationError("webhook_unavailable")
    webhook, owner_workspace_id = webhook_row

    verified = await plugin.event_definition.verify(db, webhook, request)
    if verified.connection_id != webhook.connection_id:
        raise WebhookVerificationError("connection_mismatch")
    payload = (
        verified.payload
        if len(request.raw_body) <= settings.INTEGRATIONS_EVENT_PAYLOAD_MAX_BYTES
        else None
    )
    event_id = uuid4()
    inserted_id = await db.scalar(
        insert(IntegrationEvent)
        .values(
            id=event_id,
            provider_key=provider_key,
            connection_id=verified.connection_id,
            webhook_id=webhook.id,
            external_event_id=verified.external_event_id,
            external_resource_id=verified.external_resource_id,
            event_type=verified.event_type,
            payload_digest=request.payload_digest,
            payload=payload,
            dedup_key=verified.dedup_key,
            received_at=datetime.now(UTC),
            status="received",
        )
        .on_conflict_do_nothing(
            constraint="uq_integration_events_provider_dedup",
        )
        .returning(IntegrationEvent.id)
    )
    if inserted_id is None:
        return False
    await enqueue_job(
        db,
        kind=PROCESS_EVENT_KIND,
        workspace_id=owner_workspace_id,
        subject_type="integration_event",
        subject_id=inserted_id,
        payload={"event_id": str(inserted_id)},
        content_hash=f"integration-event:{inserted_id}",
    )
    return True
