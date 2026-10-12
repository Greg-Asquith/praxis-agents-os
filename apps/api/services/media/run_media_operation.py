# apps/api/services/media/run_media_operation.py

"""Runs one typed operation on the isolated media renderer."""

from datetime import timedelta
from uuid import UUID, uuid4

import httpx2 as httpx
from pydantic import ValidationError

from core.settings import settings
from models.files import FileRevision
from services.files.contract import FileCategory, contract_for_content_type
from services.files.utils import private_ref_from_key
from services.media.domain import (
    OUTPUT_TYPES,
    RESULT_MODELS,
    FramesOperation,
    MediaOperation,
    MediaOperationResult,
    MediaRendererError,
    StagedMediaOutput,
)
from services.media.media_renderer_available import media_renderer_available
from services.media.utils import (
    discard_staged_outputs,
    renderer_auth_headers,
    renderer_transfer_url,
    staging_ref,
)
from services.storage.factory import get_storage_provider

# The renderer's budget covers its transfers; this covers cold start and the round trip.
REQUEST_ALLOWANCE_SECONDS = 60


async def run_media_operation(
    *,
    workspace_id: UUID,
    source: FileRevision,
    operation: MediaOperation,
) -> MediaOperationResult:
    """Sends one operation on an authorised workspace video and returns its staged outputs.

    The caller must have resolved ``source`` for ``workspace_id``. The renderer
    receives one signed GET for that revision and signed PUTs under this
    workspace's staging prefix; it never sees a storage name it could change.
    """
    if not media_renderer_available():
        raise MediaRendererError("unavailable", "The media renderer isn't available.")
    if source.scope != "workspace" or source.workspace_id != workspace_id:
        raise MediaRendererError("forbidden", "The video isn't in this workspace.")
    if contract_for_content_type(source.content_type).category != FileCategory.VIDEO:
        raise MediaRendererError("unsupported", "The file isn't a video.")

    provider = get_storage_provider()
    expires_in = timedelta(seconds=settings.MEDIA_STAGING_URL_TTL_SECONDS)
    download = await provider.create_signed_download(
        private_ref_from_key(source.object_key), expires_in=expires_in
    )
    request_id = uuid4()
    output_count = _output_count(operation)
    content_type, extension = OUTPUT_TYPES.get(operation.name, ("", ""))
    staged_refs = [
        staging_ref(workspace_id, request_id, index, extension) for index in range(output_count)
    ]
    uploads = [
        await provider.create_signed_staging_upload(
            ref,
            content_type=content_type,
            max_size_bytes=settings.MEDIA_RENDERER_MAX_OUTPUT_BYTES,
            expires_in=expires_in,
        )
        for ref in staged_refs
    ]
    payload = {
        "operation": operation.name,
        "timeout_seconds": settings.MEDIA_RENDERER_TIMEOUT_SECONDS,
        "input": {
            "url": renderer_transfer_url(download.url),
            "headers": download.headers,
            "size_bytes": source.size_bytes,
        },
        "outputs": [
            {"url": renderer_transfer_url(upload.url), "headers": upload.headers}
            for upload in uploads
        ],
        "arguments": operation.renderer_arguments(),
    }
    try:
        body = await _post(payload)
        return await _read_response(body, operation, staged_refs, content_type, extension)
    except BaseException:
        await discard_staged_outputs(staged_refs)
        raise


def _output_count(operation: MediaOperation) -> int:
    if isinstance(operation, FramesOperation):
        return len(operation.times_ms)
    return 1 if operation.name in OUTPUT_TYPES else 0


async def _post(payload: dict) -> dict:
    timeout = settings.MEDIA_RENDERER_TIMEOUT_SECONDS + REQUEST_ALLOWANCE_SECONDS
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{settings.MEDIA_RENDERER_URL}/v1/operations",
                json=payload,
                headers=await renderer_auth_headers(),
            )
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise MediaRendererError("unavailable", "The media renderer couldn't be reached.") from exc
    if not isinstance(body, dict):
        raise MediaRendererError("invalid_response", "The media renderer gave an invalid answer.")
    if response.status_code != 200 or body.get("ok") is not True:
        error = body.get("error") if isinstance(body.get("error"), dict) else {}
        raise MediaRendererError(
            str(error.get("code") or "failed")[:64],
            str(error.get("message") or "The media renderer failed.")[:300],
        )
    return body


async def _read_response(
    body: dict,
    operation: MediaOperation,
    staged_refs: list,
    content_type: str,
    extension: str,
) -> MediaOperationResult:
    try:
        result = RESULT_MODELS[operation.name].model_validate(body.get("result"))
    except ValidationError as exc:
        raise MediaRendererError(
            "invalid_response", "The media renderer gave an invalid answer."
        ) from exc
    reported = body.get("outputs")
    if not isinstance(reported, list) or len(reported) != len(staged_refs):
        raise MediaRendererError("invalid_response", "The media renderer gave an invalid answer.")
    provider = get_storage_provider()
    outputs = []
    for ref, item in zip(staged_refs, reported, strict=True):
        stored = await provider.stat_object(ref)
        size = item.get("size_bytes") if isinstance(item, dict) else None
        digest = item.get("sha256") if isinstance(item, dict) else None
        # Trust only what is in staging, and only when it matches what the renderer reported.
        if (
            stored is None
            or stored.size_bytes != size
            or stored.size_bytes > settings.MEDIA_RENDERER_MAX_OUTPUT_BYTES
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            raise MediaRendererError("invalid_response", "The media renderer output is missing.")
        outputs.append(
            StagedMediaOutput(
                ref=ref,
                content_type=content_type,
                extension=extension,
                size_bytes=stored.size_bytes,
                sha256=digest,
            )
        )
    return MediaOperationResult(
        result=result, outputs=tuple(outputs), elapsed_ms=int(body.get("elapsed_ms") or 0)
    )
