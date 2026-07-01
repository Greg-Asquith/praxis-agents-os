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
) -> Response:
    # Local dev provider only: buffer the body because the real cloud adapters
    # use provider-native direct uploads instead of proxying bytes here.
    body = await request.body()
    await accept_signed_upload(
        bucket,
        object_key,
        expires=expires,
        signature=sig,
        content_type=content_type,
        request_content_type=request.headers.get("content-type") or "",
        data=body,
    )
    return Response(status_code=204)
