# apps/api/services/storage/serve_private_object.py

"""Serve a signed private storage object through the active provider."""

from fastapi.responses import Response

from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from services.storage.paths import build_content_disposition
from services.storage.utils import (
    storage_object_headers,
    storage_object_not_found,
    storage_object_response,
)


async def serve_private_object(
    object_key: str,
    *,
    expires: int,
    signature: str,
    force_download: bool = False,
    filename: str | None = None,
) -> Response:
    """Return a signed private object response for the configured provider."""
    provider = get_storage_provider()
    ref = make_storage_object_ref(StorageBucket.PRIVATE, object_key)
    provider.require_valid_download_signature(
        ref=ref,
        expires=expires,
        signature=signature,
        force_download=force_download,
        filename=filename or "",
    )

    stored = await provider.stat_object(ref)
    if stored is None:
        raise storage_object_not_found(provider, ref, operation="serve_private_object")

    headers = storage_object_headers(stored)
    disposition = build_content_disposition(filename) if force_download else None
    if disposition:
        headers["Content-Disposition"] = disposition
    return await storage_object_response(provider, ref, stored, headers=headers)
