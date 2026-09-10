# apps/api/routes/storage/private_object.py

"""Serve signed private storage objects."""

from typing import Annotated

from fastapi import APIRouter, Path, Query
from fastapi.responses import Response

from services.storage import serve_private_object
from services.storage.domain import StorageBucket

router = APIRouter()


@router.get("/private/{object_key:path}")
async def get_private_storage_object(
    object_key: Annotated[str, Path()],
    expires: Annotated[int, Query()],
    sig: Annotated[str, Query()],
    bucket: Annotated[StorageBucket, Query()] = StorageBucket.PRIVATE,
    download: Annotated[str | None, Query()] = None,
    filename: Annotated[str | None, Query()] = None,
) -> Response:
    return await serve_private_object(
        object_key,
        bucket=bucket,
        expires=expires,
        signature=sig,
        force_download=download == "1",
        filename=filename,
    )
