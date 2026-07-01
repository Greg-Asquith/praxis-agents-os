# apps/api/routes/storage/public_object.py

"""Serve public storage objects."""

from typing import Annotated

from fastapi import APIRouter, Path
from fastapi.responses import Response

from services.storage import serve_public_object

router = APIRouter()


@router.get("/public/{object_key:path}")
async def get_public_storage_object(
    object_key: Annotated[str, Path()],
) -> Response:
    return await serve_public_object(object_key)
