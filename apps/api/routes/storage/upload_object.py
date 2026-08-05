# apps/api/routes/storage/upload_object.py

"""Accept signed storage uploads."""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import Response

from services.storage import accept_signed_upload
from services.storage.domain import StorageBucket

router = APIRouter()


@router.put("/upload/{bucket}/{object_key:path}", status_code=204)
async def upload_storage_object(
    request: Request,
    bucket: Annotated[StorageBucket, Path()],
    object_key: Annotated[str, Path()],
    expires: Annotated[int, Query()],
    sig: Annotated[str, Query()],
    content_type: Annotated[str, Query()],
    size_bytes: Annotated[int, Query(ge=1)],
) -> Response:
    content_length_value = request.headers.get("content-length")
    try:
        content_length = int(content_length_value) if content_length_value is not None else None
    except ValueError:
        content_length = None
    await accept_signed_upload(
        bucket,
        object_key,
        expires=expires,
        signature=sig,
        content_type=content_type,
        expected_size_bytes=size_bytes,
        request_content_type=request.headers.get("content-type") or "",
        request_content_length=content_length,
        chunks=request.stream(),
    )
    return Response(status_code=204)
