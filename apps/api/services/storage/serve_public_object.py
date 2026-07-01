# apps/api/services/storage/serve_public_object.py

"""Serve a public storage object through the active provider."""

from fastapi.responses import RedirectResponse, Response

from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from services.storage.providers.local import LocalStorageProvider
from services.storage.utils import (
    storage_object_headers,
    storage_object_not_found,
    storage_object_response,
)


async def serve_public_object(object_key: str) -> Response:
    """Return a public object response for the configured storage provider."""
    provider = get_storage_provider()
    ref = make_storage_object_ref(StorageBucket.PUBLIC, object_key)
    stored = await provider.stat_object(ref)
    if stored is None:
        raise storage_object_not_found(provider, ref, operation="serve_public_object")

    headers = storage_object_headers(stored)
    public_url = provider.public_url(ref)
    if public_url and not isinstance(provider, LocalStorageProvider):
        return RedirectResponse(public_url, status_code=307, headers=headers)

    return await storage_object_response(provider, ref, stored, headers=headers)
