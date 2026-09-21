# apps/api/integrations/sharepoint/operations/upload_session.py

"""Uploads sequential fragments and preserves uncertain commit evidence."""

import asyncio
import re
from dataclasses import dataclass

from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import MicrosoftGraphClient

from .utils import ITEM_SELECT, file_error, invalid_response, object_payload
from .write_utils import (
    DriveWriteState,
    unverified_write,
    verify_uploaded_item,
    written_item,
)

FRAGMENT_BYTES = 10 * 1024 * 1024
MAX_RESUMES = 3
_MISSING_RANGE = re.compile(r"([0-9]{1,20})-(?:[0-9]{1,20})?")


@dataclass(frozen=True)
class UploadTarget:
    drive_id: str
    session_path: str
    item_path: str
    operation: str
    item_id: str | None = None
    expected_version: str | None = None
    name: str | None = None
    parent_id: str | None = None


def _next_offset(payload: dict, *, total: int, maximum: int, minimum: int, operation: str) -> int:
    ranges = payload.get("nextExpectedRanges")
    if not isinstance(ranges, list) or len(ranges) != 1:
        raise invalid_response(operation)
    match = _MISSING_RANGE.fullmatch(ranges[0]) if isinstance(ranges[0], str) else None
    if match is None:
        raise invalid_response(operation)
    offset = int(match[1])
    if offset >= total or not minimum <= offset <= maximum or offset % (320 * 1024):
        raise invalid_response(operation)
    return offset


async def _cancel(client: MicrosoftGraphClient, url: str, operation: str) -> None:
    try:
        async with asyncio.timeout(5):
            await client.cancel_upload(url, operation=operation)
    except (IntegrationError, TimeoutError):
        pass


async def _committed_item(
    payload: dict,
    *,
    target: UploadTarget,
    data: bytes,
    state: DriveWriteState,
) -> dict:
    if target.item_id is not None and payload.get("id") != target.item_id:
        raise unverified_write(target.operation, state)
    try:
        result = written_item(
            payload,
            drive_id=target.drive_id,
            operation=target.operation,
            state=state,
            kind="file",
            name=target.name,
            parent_id=target.parent_id,
        )
    except IntegrationError:
        raise unverified_write(target.operation, state) from None
    state.hash_matched = await asyncio.to_thread(verify_uploaded_item, payload, data=data)
    if not state.hash_matched:
        raise unverified_write(target.operation, state)
    state.bytes_sent = len(data)
    return result


async def _reconcile(
    client: MicrosoftGraphClient,
    url: str,
    *,
    target: UploadTarget,
    data: bytes,
    state: DriveWriteState,
) -> dict:
    try:
        state.session_status = await _reconciliation_status(client, url, target.operation)
        payload = object_payload(
            await client.get(
                target.item_path,
                operation=target.operation,
                policy=IntegrationRequestPolicy.READ,
                params={"$select": ITEM_SELECT},
            ),
            operation=target.operation,
        )
        # Destination content is observational evidence, not a receipt for this upload.
        if not await asyncio.to_thread(verify_uploaded_item, payload, data=data):
            raise unverified_write(target.operation, state)
        if target.item_id is not None and payload.get("id") != target.item_id:
            raise unverified_write(target.operation, state)
        written_item(
            payload,
            drive_id=target.drive_id,
            operation=target.operation,
            state=state,
            kind="file",
            name=target.name,
            parent_id=target.parent_id,
        )
        state.hash_matched = True
    except IntegrationError:
        raise unverified_write(target.operation, state) from None
    except asyncio.CancelledError as exc:
        exc.failure_disposition = IntegrationFailureDisposition.AMBIGUOUS
        raise
    raise unverified_write(target.operation, state)


async def _reconciliation_status(client: MicrosoftGraphClient, url: str, operation: str) -> str:
    try:
        payload = await client.upload_status(url, operation=operation)
    except IntegrationError as exc:
        return "missing" if exc.error_code == "upload_session_expired" else "unavailable"
    ranges = payload.get("nextExpectedRanges")
    if not isinstance(ranges, list) or not ranges:
        return "unknown"
    return (
        "incomplete"
        if all(isinstance(value, str) and _MISSING_RANGE.fullmatch(value) for value in ranges)
        else "unknown"
    )


async def _fragment(
    client: MicrosoftGraphClient,
    url: str,
    *,
    target: UploadTarget,
    data: bytes,
    offset: int,
    state: DriveWriteState,
) -> dict:
    chunk = data[offset : offset + FRAGMENT_BYTES]
    state.final_fragment_started = offset + len(chunk) == len(data)
    payload = await client.upload_fragment(
        url, chunk, operation=target.operation, offset=offset, total=len(data)
    )
    state.bytes_sent = max(state.bytes_sent, offset + len(chunk))
    return payload


async def _send_fragments(
    client: MicrosoftGraphClient,
    url: str,
    *,
    target: UploadTarget,
    data: bytes,
    state: DriveWriteState,
) -> dict:
    offset = 0
    resumes = 0
    while offset < len(data):
        attempted_end = min(offset + FRAGMENT_BYTES, len(data))
        minimum = attempted_end
        try:
            payload = await _fragment(
                client, url, target=target, data=data, offset=offset, state=state
            )
        except IntegrationError as exc:
            if state.final_fragment_started:
                return await _final_failure(
                    client, url, target=target, data=data, state=state, exc=exc
                )
            if exc.error_code != "upload_interrupted" or resumes >= MAX_RESUMES:
                raise
            resumes += 1
            await asyncio.sleep(2 ** (resumes - 1))
            payload = await client.upload_status(url, operation=target.operation)
            minimum = 0
        if "id" in payload:
            if not state.final_fragment_started:
                raise invalid_response(target.operation)
            state.committed = True
            return await _committed_item(payload, target=target, data=data, state=state)
        if state.final_fragment_started:
            raise unverified_write(target.operation, state)
        offset = _next_offset(
            payload,
            total=len(data),
            maximum=attempted_end,
            minimum=minimum,
            operation=target.operation,
        )
        state.bytes_sent = max(state.bytes_sent, offset)
    raise unverified_write(target.operation, state)


async def _final_failure(
    client: MicrosoftGraphClient,
    url: str,
    *,
    target: UploadTarget,
    data: bytes,
    state: DriveWriteState,
    exc: IntegrationError,
) -> dict:
    if exc.failure_disposition is IntegrationFailureDisposition.AMBIGUOUS:
        return await _reconcile(client, url, target=target, data=data, state=state)
    raise exc


async def run_upload_session(
    client: MicrosoftGraphClient,
    *,
    target: UploadTarget,
    data: bytes,
    state: DriveWriteState,
) -> dict:
    if not data:
        raise file_error(
            "Enter non-empty file content.", "empty_content", operation=target.operation
        )
    url = await _create_session(client, target=target)
    state.session_created = True
    try:
        return await _send_fragments(client, url, target=target, data=data, state=state)
    except IntegrationError as exc:
        if not state.final_fragment_started:
            await _cancel(client, url, target.operation)
            exc.failure_disposition = IntegrationFailureDisposition.NOT_DISPATCHED
        raise
    except asyncio.CancelledError as exc:
        if not state.final_fragment_started:
            exc.failure_disposition = IntegrationFailureDisposition.NOT_DISPATCHED
            await _cancel(client, url, target.operation)
        raise


async def _create_session(client: MicrosoftGraphClient, *, target: UploadTarget) -> str:
    try:
        payload = object_payload(
            await client.post(
                target.session_path,
                operation=target.operation,
                policy=IntegrationRequestPolicy.MUTATION,
                json={"item": {"@microsoft.graph.conflictBehavior": "fail"}},
                headers={"If-Match": target.expected_version} if target.expected_version else None,
            ),
            operation=target.operation,
        )
        url = payload.get("uploadUrl")
        if not isinstance(url, str) or not url:
            raise invalid_response(target.operation)
        return url
    except (IntegrationError, asyncio.CancelledError) as exc:
        # Creating the session alone cannot replace or publish file content.
        exc.failure_disposition = IntegrationFailureDisposition.NOT_DISPATCHED
        raise
