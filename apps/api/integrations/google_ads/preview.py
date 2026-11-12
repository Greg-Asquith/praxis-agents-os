# apps/api/integrations/google_ads/preview.py

"""Google Ads image assets for the generic integration preview route."""

import re

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationValidationError
from models.integrations import IntegrationConnection
from services.integrations.plugin import (
    IntegrationPreviewDefinition,
    IntegrationPreviewPayload,
    IntegrationPreviewRequest,
)

PREVIEW_OPERATION = "preview_google_ads_image"
_REF = re.compile(r"[0-9]{1,20}")


async def fetch_image_preview(
    db: AsyncSession, connection: IntegrationConnection, request: IntegrationPreviewRequest
) -> IntegrationPreviewPayload:
    """Returns a picture of an image asset in the conversation's Google Ads account."""
    # Resolve at call time so tests can replace the operation without rebuilding the plugin.
    from .operations.preview_image import preview_image
    from .tools.utils import google_ads_client_for_principal, login_customer_id

    entry = request.scope
    if entry is None or entry.connection_id != connection.id:
        raise IntegrationValidationError(
            "A Google Ads image preview needs an account from the conversation.",
            provider_key="google_ads",
            operation=PREVIEW_OPERATION,
        )
    client = await google_ads_client_for_principal(
        db, actor=request.actor, workspace=request.workspace, entry=entry
    )
    content, width, height = await preview_image(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        asset_id=request.ref,
    )
    return IntegrationPreviewPayload(
        content_type="image", content=content, meta={"width": width, "height": height}
    )


GOOGLE_ADS_IMAGE_PREVIEW = IntegrationPreviewDefinition(
    kind="google_ads_image",
    operation=PREVIEW_OPERATION,
    fetch=fetch_image_preview,
    ref_pattern=_REF,
)
