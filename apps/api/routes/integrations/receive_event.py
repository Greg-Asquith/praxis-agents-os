# apps/api/routes/integrations/receive_event.py

"""Receive one cryptographically authenticated provider event."""

import hashlib
from typing import Annotated

from fastapi import APIRouter, Path, Request, Response, status

from core.dependencies import AsyncDbSessionDep
from core.exceptions.general import RequestBodyTooLargeError
from core.exceptions.integration import IntegrationAuthError
from core.rate_limiting import enforce_rate_limit, get_client_ip
from core.settings import settings
from services.integrations.events import (
    WebhookVerificationError,
    receive_event as receive_event_service,
)
from services.integrations.plugin import IntegrationEventRequest
from services.security import SecurityEventType, safe_record_security_event_committed

router = APIRouter()


@router.post(
    "/events/{provider_key}/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def receive_event(
    provider_key: Annotated[
        str,
        Path(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$"),
    ],
    webhook_id: Annotated[
        str,
        Path(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$"),
    ],
    request: Request,
    db: AsyncDbSessionDep,
) -> Response:
    client_ip = get_client_ip(request)
    await enforce_rate_limit(
        subject_ip=client_ip,
        endpoint=f"{settings.API_V1_PREFIX}/integrations/events/{provider_key}",
        limit_type="integration_webhook_receipts",
        custom_limit=settings.INTEGRATIONS_EVENT_RECEIPTS_PER_MINUTE,
        custom_window=60,
    )
    raw_body = await _read_bounded_body(request)
    payload_digest = hashlib.sha256(raw_body).hexdigest()
    event_request = IntegrationEventRequest(
        headers={key.lower(): value for key, value in request.headers.items()},
        raw_body=raw_body,
        payload_digest=payload_digest,
        request_url=str(request.url),
    )
    try:
        await receive_event_service(
            db,
            provider_key=provider_key,
            receipt_id=webhook_id,
            request=event_request,
        )
    except WebhookVerificationError as exc:
        await safe_record_security_event_committed(
            event_type=SecurityEventType.INTEGRATION_WEBHOOK_REJECTED,
            ip_address=client_ip,
            endpoint=request.url.path,
            request_id=request.scope.get("request_id"),
            details={
                "provider_key": provider_key,
                "webhook_id_fingerprint": hashlib.sha256(webhook_id.encode()).hexdigest(),
                "reason_code": exc.reason_code,
                "payload_digest": payload_digest,
            },
        )
        raise IntegrationAuthError(
            "Integration webhook verification failed",
            provider_key=provider_key,
            operation="verify_webhook",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _read_bounded_body(request: Request) -> bytes:
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > settings.INTEGRATIONS_EVENT_RECEIPT_MAX_BYTES:
            raise RequestBodyTooLargeError(
                "Integration event receipt is too large",
                details={"max_bytes": settings.INTEGRATIONS_EVENT_RECEIPT_MAX_BYTES},
            )
        chunks.append(chunk)
    return b"".join(chunks)
