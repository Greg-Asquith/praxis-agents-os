# apps/api/services/agents/runtime/staged_tool_content.py

"""Stage and redact durable write_file content for approval flows."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic_ai import DeferredToolRequests
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ToolCallPart

from core.exceptions.general import AppValidationError
from services.files.utils import private_ref_from_key
from services.storage.errors import StorageValidationError
from services.storage.factory import get_storage_provider
from services.storage.paths import validate_object_key

WRITE_FILE_TOOL_NAME = "write_file"
WRITE_FILE_CONTENT_REF_ARG = "content_ref"

_DISPLAY_ARGS_METADATA_KEY = "display_args"
_REDACTED_CONTENT = "[staged for approval; content omitted]"
_STAGED_WRITE_REF_PATTERN = re.compile(r"[0-9a-f]{64}-[0-9a-f]{64}\.txt")


@dataclass(frozen=True)
class StagedDeferredToolContent:
    """Messages and approvals with bulky tool content replaced by staged refs."""

    new_messages: list[ModelMessage]
    all_messages: list[ModelMessage]
    deferred_tool_requests: DeferredToolRequests


async def stage_write_file_approval_content(
    *,
    workspace_id: UUID,
    run_id: UUID,
    new_messages: Sequence[ModelMessage],
    all_messages: Sequence[ModelMessage],
    deferred_tool_requests: DeferredToolRequests,
) -> StagedDeferredToolContent:
    """Stage durable write_file content and redact deferred approval args."""
    staged_args_by_call_id: dict[str, dict[str, Any]] = {}
    metadata = {
        call_id: dict(value) for call_id, value in (deferred_tool_requests.metadata or {}).items()
    }

    provider = get_storage_provider()
    for approval in deferred_tool_requests.approvals:
        args = _mapping_args(approval.args)
        if not _needs_staging(approval, args):
            continue

        content = args["content"]
        data = content.encode("utf-8")
        content_hash = hashlib.sha256(data).hexdigest()
        object_key = _staged_write_object_key(
            workspace_id=workspace_id,
            run_id=run_id,
            tool_call_id=approval.tool_call_id,
            content_hash=content_hash,
        )
        await provider.put_object(
            private_ref_from_key(object_key),
            data,
            content_type="text/plain",
            metadata={
                "tool_name": WRITE_FILE_TOOL_NAME,
                "tool_call_id": approval.tool_call_id,
                "content_sha256": content_hash,
            },
        )

        staged_args = dict(args)
        staged_args.pop("content", None)
        staged_args[WRITE_FILE_CONTENT_REF_ARG] = object_key
        staged_args_by_call_id[approval.tool_call_id] = staged_args
        metadata[approval.tool_call_id] = {
            **metadata.get(approval.tool_call_id, {}),
            _DISPLAY_ARGS_METADATA_KEY: _safe_write_file_args(
                args,
                content_bytes=len(data),
                content_sha256=content_hash,
            ),
        }

    if not staged_args_by_call_id:
        return StagedDeferredToolContent(
            new_messages=list(new_messages),
            all_messages=list(all_messages),
            deferred_tool_requests=deferred_tool_requests,
        )

    return StagedDeferredToolContent(
        new_messages=_sanitize_messages(new_messages, staged_args_by_call_id),
        all_messages=_sanitize_messages(all_messages, staged_args_by_call_id),
        deferred_tool_requests=DeferredToolRequests(
            calls=list(deferred_tool_requests.calls),
            approvals=[
                _copy_tool_call(
                    approval,
                    args=staged_args_by_call_id.get(approval.tool_call_id, approval.args),
                )
                for approval in deferred_tool_requests.approvals
            ],
            metadata=metadata,
        ),
    )


def tool_args_for_display(
    *,
    tool_name: str,
    args: Any,
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """Return model/user-facing tool args with sensitive write content redacted."""
    if isinstance(metadata, Mapping):
        display_args = metadata.get(_DISPLAY_ARGS_METADATA_KEY)
        if isinstance(display_args, Mapping):
            return dict(display_args)

    if tool_name != WRITE_FILE_TOOL_NAME:
        return args

    mapped_args = _mapping_args(args)
    if mapped_args is None or mapped_args.get("destination") != "file":
        return args
    return _safe_write_file_args(mapped_args)


async def resolve_staged_write_content(
    *,
    workspace_id: UUID,
    run_id: UUID,
    content_ref: str,
) -> str:
    """Load staged durable write content for an approved write_file replay."""
    object_key = _validate_staged_write_ref(
        workspace_id=workspace_id,
        run_id=run_id,
        content_ref=content_ref,
    )
    data = await get_storage_provider().get_object(private_ref_from_key(object_key))
    return data.decode("utf-8", errors="replace")


async def delete_staged_write_content(
    *,
    workspace_id: UUID,
    run_id: UUID,
    content_ref: str,
) -> None:
    """Best-effort cleanup for staged durable write content."""
    object_key = _validate_staged_write_ref(
        workspace_id=workspace_id,
        run_id=run_id,
        content_ref=content_ref,
    )
    await get_storage_provider().delete_object(private_ref_from_key(object_key))


def _needs_staging(approval: ToolCallPart, args: Mapping[str, Any] | None) -> bool:
    return (
        approval.tool_name == WRITE_FILE_TOOL_NAME
        and args is not None
        and args.get("destination") == "file"
        and isinstance(args.get("content"), str)
        and not args.get(WRITE_FILE_CONTENT_REF_ARG)
    )


def _mapping_args(args: Any) -> dict[str, Any] | None:
    if isinstance(args, Mapping):
        return dict(args)
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, Mapping):
            return dict(parsed)
    return None


def _safe_write_file_args(
    args: Mapping[str, Any],
    *,
    content_bytes: int | None = None,
    content_sha256: str | None = None,
) -> dict[str, Any]:
    safe_args = {
        key: args[key]
        for key in (
            "destination",
            "name",
            "file_id",
            "expected_current_revision_id",
        )
        if key in args
    }
    if "content" in args or WRITE_FILE_CONTENT_REF_ARG in args:
        safe_args["content"] = _REDACTED_CONTENT
    if content_bytes is None and isinstance(args.get("content"), str):
        content_bytes = len(args["content"].encode("utf-8"))
    if content_bytes is not None:
        safe_args["content_bytes"] = content_bytes
    if content_sha256 is not None:
        safe_args["content_sha256"] = content_sha256
    return safe_args


def _sanitize_messages(
    messages: Sequence[ModelMessage],
    staged_args_by_call_id: Mapping[str, Mapping[str, Any]],
) -> list[ModelMessage]:
    serialized = json.loads(ModelMessagesTypeAdapter.dump_json(list(messages)))
    for message in serialized:
        if not isinstance(message, dict):
            continue
        for part in message.get("parts", []):
            if not isinstance(part, dict) or part.get("part_kind") != "tool-call":
                continue
            tool_call_id = part.get("tool_call_id")
            if isinstance(tool_call_id, str) and tool_call_id in staged_args_by_call_id:
                part["args"] = dict(staged_args_by_call_id[tool_call_id])
    return list(ModelMessagesTypeAdapter.validate_python(serialized))


def _copy_tool_call(part: ToolCallPart, *, args: Any) -> ToolCallPart:
    return ToolCallPart(
        tool_name=part.tool_name,
        args=args,
        tool_call_id=part.tool_call_id,
        tool_kind=part.tool_kind,
        id=part.id,
        provider_name=part.provider_name,
        provider_details=part.provider_details,
    )


def _staged_write_object_key(
    *,
    workspace_id: UUID,
    run_id: UUID,
    tool_call_id: str,
    content_hash: str,
) -> str:
    call_hash = hashlib.sha256(tool_call_id.encode("utf-8")).hexdigest()
    return (
        f"{_staged_write_prefix(workspace_id=workspace_id, run_id=run_id)}"
        f"{call_hash}-{content_hash}.txt"
    )


def _validate_staged_write_ref(
    *,
    workspace_id: UUID,
    run_id: UUID,
    content_ref: str,
) -> str:
    try:
        object_key = validate_object_key(content_ref)
    except StorageValidationError as exc:
        raise AppValidationError(
            "Invalid staged file content reference", field="content_ref"
        ) from exc

    prefix = _staged_write_prefix(workspace_id=workspace_id, run_id=run_id)
    if not object_key.startswith(prefix):
        raise AppValidationError("Invalid staged file content reference", field="content_ref")

    suffix = object_key.removeprefix(prefix)
    if _STAGED_WRITE_REF_PATTERN.fullmatch(suffix) is None:
        raise AppValidationError("Invalid staged file content reference", field="content_ref")
    return object_key


def _staged_write_prefix(*, workspace_id: UUID, run_id: UUID) -> str:
    return f"workspaces/{workspace_id}/agent-runs/{run_id}/staged-tool-inputs/"
