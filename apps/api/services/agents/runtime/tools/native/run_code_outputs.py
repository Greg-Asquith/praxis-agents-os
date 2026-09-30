# apps/api/services/agents/runtime/tools/native/run_code_outputs.py

"""Bounded capture of native ``run_code`` outputs. Persistence lives in `services.documents.outputs`."""

import hashlib
import mimetypes
import re
from collections.abc import AsyncIterator, Mapping, Sequence, Set
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any
from urllib.parse import unquote

from pydantic_ai.messages import (
    FilePart,
    ModelMessage,
    ModelResponse,
    NativeToolCallPart,
    NativeToolReturnPart,
)
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIResponsesModel

from core.settings import settings
from services.documents.outputs import CapturedOutput, StoredOutput, safe_sandbox_name

_TRUNCATED_MARKER = "\n[truncated]"
_SANDBOX_MARKDOWN_LINK = re.compile(
    r"(?P<label>\[[^\]]+\])\((?P<target>sandbox:[^)]+)\)",
    flags=re.IGNORECASE,
)


@dataclass
class _RetrievalBudget:
    """Bounds provider output downloads before the bytes enter worker memory."""

    files_remaining: int
    bytes_remaining: int
    skipped: list[str]
    _limit_noted: bool = field(default=False, repr=False)

    def exhausted(self) -> bool:
        if self.files_remaining > 0 and self.bytes_remaining > 0:
            return False
        if not self._limit_noted:
            self._limit_noted = True
            self.skipped.append("Further sandbox outputs were not retrieved: output limits reached")
        return True

    def admit(self, name: str, declared_size: int | None) -> bool:
        if self.exhausted():
            return False
        if declared_size is not None and declared_size > self.bytes_remaining:
            self.skipped.append(f"{name}: output byte limit exceeded")
            return False
        return True

    def record(self, name: str, size: int) -> bool:
        if size > self.bytes_remaining:
            self.skipped.append(f"{name}: output byte limit exceeded")
            return False
        self.files_remaining -= 1
        self.bytes_remaining -= size
        return True

    async def read(self, name: str, chunks: AsyncIterator[bytes]) -> bytes | None:
        """Buffer a streamed download, stopping as soon as it exceeds the remaining bytes."""
        buffer = bytearray()
        async for chunk in chunks:
            buffer.extend(chunk)
            if len(buffer) > self.bytes_remaining:
                self.skipped.append(f"{name}: output byte limit exceeded")
                return None
        content = bytes(buffer)
        return content if self.record(name, len(content)) else None


def _declared_size(metadata: object, attribute: str) -> int | None:
    value = getattr(metadata, attribute, None)
    return value if isinstance(value, int) else None


async def capture_sandbox_files(
    provider_model: object,
    messages: Sequence[ModelMessage],
    *,
    excluded_hashes: Set[str] = frozenset(),
    excluded_provider_file_ids: Set[str] = frozenset(),
) -> tuple[list[CapturedOutput], list[str]]:
    inline = _inline_files(messages)
    skipped: list[str] = []
    budget = _RetrievalBudget(
        files_remaining=max(0, settings.NATIVE_RUN_CODE_MAX_OUTPUT_FILES - len(inline)),
        bytes_remaining=max(
            0,
            settings.NATIVE_RUN_CODE_MAX_OUTPUT_BYTES - sum(len(item.content) for item in inline),
        ),
        skipped=skipped,
    )
    # Provider-named copies go first so hash dedup keeps the sandbox filename over a
    # synthetic inline name; the same bytes can arrive through both channels.
    captured: list[CapturedOutput] = []
    try:
        if isinstance(provider_model, OpenAIResponsesModel):
            captured.extend(
                await _openai_container_files(
                    provider_model,
                    messages,
                    budget,
                    excluded_provider_file_ids=excluded_provider_file_ids,
                )
            )
        elif isinstance(provider_model, AnthropicModel):
            captured.extend(await _anthropic_output_files(provider_model, messages, budget))
    except Exception as exc:
        skipped.append(f"Provider output retrieval failed: {type(exc).__name__}")
    captured.extend(inline)
    deduped: list[CapturedOutput] = []
    hashes: set[str] = set()
    total_bytes = 0
    for item in captured:
        digest = hashlib.sha256(item.content).hexdigest()
        if digest in excluded_hashes or digest in hashes:
            continue
        hashes.add(digest)
        if len(deduped) >= settings.NATIVE_RUN_CODE_MAX_OUTPUT_FILES:
            skipped.append(f"{item.name}: output file limit exceeded")
            continue
        if total_bytes + len(item.content) > settings.NATIVE_RUN_CODE_MAX_OUTPUT_BYTES:
            skipped.append(f"{item.name}: output byte limit exceeded")
            continue
        total_bytes += len(item.content)
        deduped.append(item)
    return deduped, skipped


def _inline_files(messages: Sequence[ModelMessage]) -> list[CapturedOutput]:
    output: list[CapturedOutput] = []
    index = 0
    for message in messages:
        if not isinstance(message, ModelResponse):
            continue
        for part in message.parts:
            if not isinstance(part, FilePart):
                continue
            index += 1
            extension = _extension_for_media_type(part.content.media_type)
            identifier = getattr(part.content, "identifier", None)
            name = (
                safe_sandbox_name(identifier)
                if isinstance(identifier, str) and PurePath(identifier).suffix
                else f"sandbox-output-{index}{extension}"
            )
            output.append(
                CapturedOutput(
                    name=name,
                    content=part.content.data,
                    media_type=part.content.media_type,
                )
            )
    return output


async def _openai_container_files(
    model: OpenAIResponsesModel,
    messages: Sequence[ModelMessage],
    budget: _RetrievalBudget,
    *,
    excluded_provider_file_ids: Set[str] = frozenset(),
) -> list[CapturedOutput]:
    container_ids = dict.fromkeys(
        args["container_id"]
        for args in (_part_args(part) for part in _native_calls(messages))
        if isinstance(args.get("container_id"), str)
    )
    output: list[CapturedOutput] = []
    for container_id in container_ids:
        if budget.exhausted():
            break
        async for metadata in model.client.containers.files.list(container_id):
            if budget.exhausted():
                break
            if metadata.id in excluded_provider_file_ids:
                continue
            name = safe_sandbox_name(getattr(metadata, "path", None) or metadata.id)
            if not budget.admit(name, _declared_size(metadata, "bytes")):
                continue
            response = await model.client.containers.files.content.retrieve(
                metadata.id,
                container_id=container_id,
            )
            content = await budget.read(name, await response.aiter_bytes())
            if content is None:
                continue
            output.append(
                CapturedOutput(
                    name=name,
                    content=content,
                    media_type=_media_type_for_name(name),
                )
            )
    return output


async def _anthropic_output_files(
    model: AnthropicModel,
    messages: Sequence[ModelMessage],
    budget: _RetrievalBudget,
) -> list[CapturedOutput]:
    file_ids: dict[str, None] = {}
    for message in messages:
        for part in getattr(message, "parts", ()):
            if isinstance(part, NativeToolReturnPart) and part.tool_name == "code_execution":
                _collect_file_ids(part.content, file_ids)
    output: list[CapturedOutput] = []
    for file_id in file_ids:
        if budget.exhausted():
            break
        metadata = await model.client.beta.files.retrieve_metadata(file_id)
        name = safe_sandbox_name(getattr(metadata, "filename", None) or file_id)
        if not budget.admit(name, _declared_size(metadata, "size_bytes")):
            continue
        response = await model.client.beta.files.download(file_id)
        content = await budget.read(name, response.iter_bytes())
        if content is None:
            continue
        output.append(
            CapturedOutput(
                name=name,
                content=content,
                media_type=getattr(metadata, "mime_type", None) or _media_type_for_name(name),
            )
        )
    return output


def _native_calls(messages: Sequence[ModelMessage]) -> list[NativeToolCallPart]:
    return [
        part
        for message in messages
        for part in getattr(message, "parts", ())
        if isinstance(part, NativeToolCallPart) and part.tool_name == "code_execution"
    ]


def _part_args(part: NativeToolCallPart) -> dict[str, Any]:
    return part.args if isinstance(part.args, dict) else {}


def _collect_file_ids(value: object, target: dict[str, None]) -> None:
    if isinstance(value, Mapping):
        file_id = value.get("file_id")
        if isinstance(file_id, str) and file_id:
            target.setdefault(file_id)
        for item in value.values():
            _collect_file_ids(item, target)
    elif isinstance(value, list):
        for item in value:
            _collect_file_ids(item, target)


def truncate_run_code_output(value: str) -> str:
    maximum = settings.NATIVE_RUN_CODE_OUTPUT_MAX_CHARS
    if len(value) <= maximum:
        return value
    keep = max(0, maximum - len(_TRUNCATED_MARKER))
    return value[:keep] + _TRUNCATED_MARKER


def rewrite_sandbox_links(
    value: str,
    outputs: Sequence[StoredOutput],
) -> str:
    """Replace provider-local markdown links with durable workspace entity links."""
    outputs_by_name = {output.sandbox_name or output.name: output for output in outputs}
    outputs_by_stem = {
        PurePath(output.name).stem: output for output in outputs if output.kind == "artifact"
    }

    def replace_link(match: re.Match[str]) -> str:
        label = match.group("label")
        target = unquote(match.group("target").split(":", 1)[1])
        target_name = PurePath(target).name
        output = outputs_by_name.get(target_name) or outputs_by_stem.get(PurePath(target_name).stem)
        if output is None:
            return f"{label} (sandbox output was not retained)"
        entity_id = output.reference.entity_id
        if output.kind == "artifact":
            return f"{label}(/artifacts/{entity_id})"
        return f"{label}(/files?fileId={entity_id})"

    return _SANDBOX_MARKDOWN_LINK.sub(replace_link, value)


def _media_type_for_name(name: str) -> str:
    guessed, _encoding = mimetypes.guess_type(name)
    return guessed or "application/octet-stream"


def _extension_for_media_type(media_type: str) -> str:
    overrides = {
        "image/jpeg": ".jpg",
        "text/markdown": ".md",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    }
    return overrides.get(media_type, mimetypes.guess_extension(media_type) or ".bin")
