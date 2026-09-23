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
        "Use data to inspect the result's structure and metadata. "
        "Read the full saved result through file_reference when you need rows beyond this preview. "
        "Call read_file with file_id=file_reference and offset to inspect saved rows. "
        "For filtering or calculations, call run_code with file_ids=[file_reference] when available. "
        "Calculate whole-report totals from the saved result, never from preview rows. "
        "Use each lists entry's total as its saved item count. Check provider metadata in data before "
        "requesting another source page. Do not repeat or split the source query to recover "
        "rows already saved. If you cannot read or process the saved result, report that "
        "limitation instead of refetching it."
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
