# apps/api/routes/storage/private_object.py

"""Serve signed private storage objects."""

from typing import Annotated

from fastapi import APIRouter, Path, Query
from fastapi.responses import Response

from services.storage import serve_private_object

router = APIRouter()


@router.get("/private/{object_key:path}")
async def get_private_storage_object(
    object_key: Annotated[str, Path()],
    expires: Annotated[int, Query()],
    sig: Annotated[str, Query()],
    download: Annotated[str | None, Query()] = None,
    filename: Annotated[str | None, Query()] = None,
) -> Response:
    return await serve_private_object(
        object_key,
        expires=expires,
        signature=sig,
        force_download=download == "1",
        filename=filename,
    )
