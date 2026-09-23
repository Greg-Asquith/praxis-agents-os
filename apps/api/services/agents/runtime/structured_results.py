# apps/api/services/agents/runtime/structure_results.py

"""Builds bounded previews without changing retained tool data or past messages."""

import json
from copy import deepcopy
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from services.agents.runtime.entity_references.domain import FileReference


class PreviewListCount(BaseModel):
    total: int = Field(ge=0)
    shown: int = Field(ge=0)


class StructuredResultPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview: Literal[True] = True
    file_id: UUID
    file_name: str
    file_reference: FileReference
    data: JsonValue
    lists: dict[str, PreviewListCount]
    hint: str = (
        "This is an incomplete preview. The complete returned JSON is saved internally under "
        "file_id. Use read_file with file_id=file_reference and offset to inspect windows. "
        "If run_code is available, pass file_ids=[file_reference]  to aggregate or filter all rows. "
        "Use an OpenAI or Anthropic file bridge for inputs above Google's text limit. Never calculate whole-report totals from this preview."
    )


def result_json(value: Any) -> str:
    """Serialises JSON-safe results using the measured model-facing representation."""
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def preview_structured_result(
    result: Any,
    *,
    limit: int,
    preview_rows: int,
    list_path: str | None,
    file_id: UUID,
    file_name: str,
) -> dict[str, Any]:
    """Returns the largest uniform row prefix that fits, preserving account coverage."""
    paths = _preview_paths(result, list_path)
    if not paths:
        raise ValueError("The result has no previewable lists. Narrow the query.")
    low, high = 1, preview_rows
    best = None
    data = deepcopy(result)
    while low <= high:
        rows = (low + high) // 2
        counts = {}
        for path in paths:
            original = _at_path(result, path)
            preview = original[:rows]
            if path:
                _at_path(data, path[:-1])[path[-1]] = preview
            else:
                data = preview
            counts[".".join(map(str, path)) or "$"] = PreviewListCount(
                total=len(original), shown=len(preview)
            )
        envelope = StructuredResultPreview(
            data=data,
            lists=counts,
            file_id=file_id,
            file_name=file_name,
            file_reference=FileReference(entity_id=file_id, label=file_name),
        ).model_dump(mode="json")
        if len(result_json(envelope)) <= limit:
            best = envelope
            low = rows + 1
        else:
            high = rows - 1
    if best is None:
        raise ValueError(
            "The result metadata and one row per list exceed the preview limit. Narrow the query."
        )
    return best


def _at_path(value: Any, path: tuple[str | int, ...]) -> Any:
    for key in path:
        value = value[key]
    return value


def _preview_paths(result: Any, list_path: str | None) -> list[tuple[str | int, ...]]:
    paths: list[tuple[str | int, ...]] = []
    selected = tuple(list_path.split(".")) if list_path is not None else None

    def visit(value: Any, path: tuple[str | int, ...], pattern: tuple[str, ...] | None) -> None:
        if pattern:
            key, *rest = pattern
            if key == "*" and isinstance(value, list):
                for index, item in enumerate(value):
                    visit(item, (*path, index), tuple(rest))
            elif isinstance(value, dict) and key in value:
                visit(value[key], (*path, key), tuple(rest))
            return
        if isinstance(value, list):
            # Account envelopes retain errors and identity even when their row lists shrink.
            fan_out = (
                pattern is None
                and value
                and all(
                    isinstance(item, dict) and "status" in item and "data" in item for item in value
                )
            )
            if fan_out:
                for index, item in enumerate(value):
                    visit(item, (*path, index), None)
            else:
                paths.append(path)
        elif isinstance(value, dict) and pattern is None:
            for key, item in value.items():
                visit(item, (*path, key), None)

    visit(result, (), selected)
    return paths
