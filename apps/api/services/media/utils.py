# apps/api/services/media/utils.py

"""Helpers for the media renderer client."""

import asyncio
import logging
from uuid import UUID

from core.settings import settings
from services.media.domain import MEDIA_STAGING_PREFIX, MediaRendererError, StagedMediaOutput
from services.storage.domain import StorageBucket, StorageObjectRef, make_storage_object_ref
from services.storage.factory import get_storage_provider

logger = logging.getLogger(__name__)


def staging_ref(
    workspace_id: UUID, request_id: UUID, index: int, extension: str
) -> StorageObjectRef:
    """Returns a platform staging key scoped to one workspace and one renderer request."""
    return make_storage_object_ref(
        StorageBucket.PLATFORM_PRIVATE,
        f"{MEDIA_STAGING_PREFIX}/{workspace_id}/{request_id}/output-{index}{extension}",
    )


def renderer_transfer_url(url: str) -> str:
    """Points local storage URLs at the API origin the renderer container can reach."""
    if get_storage_provider().provider_key != "local_fs":
        return url
    origin = settings.APP_BASE_URL.rstrip("/")
    if not url.startswith(f"{origin}/"):
        raise MediaRendererError("unavailable", "The media renderer can't reach local storage.")
    return settings.MEDIA_RENDERER_LOCAL_STORAGE_URL.rstrip("/") + url[len(origin) :]


async def renderer_auth_headers() -> dict[str, str]:
    """Returns the renderer's authorization header for the configured auth mode."""
    if settings.MEDIA_RENDERER_AUTH == "none":
        return {}
    if settings.MEDIA_RENDERER_AUTH == "shared_secret":
        secret = settings.MEDIA_RENDERER_SHARED_SECRET.get_secret_value()
        return {"authorization": f"Bearer {secret}"}
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import id_token
    except ImportError as exc:
        raise MediaRendererError("unavailable", "The media renderer isn't available.") from exc
    token = await asyncio.to_thread(id_token.fetch_id_token, Request(), settings.MEDIA_RENDERER_URL)
    return {"authorization": f"Bearer {token}"}


async def discard_staged_outputs(
    outputs: tuple[StagedMediaOutput, ...] | list[StorageObjectRef],
) -> None:
    """Deletes staged renderer outputs; the staging lifecycle rule removes any left behind."""
    provider = get_storage_provider()
    for item in outputs:
        ref = item.ref if isinstance(item, StagedMediaOutput) else item
        try:
            await provider.delete_object(ref)
        except Exception:
            logger.warning("Failed to delete staged media output", extra={"object_key": ref.key})
