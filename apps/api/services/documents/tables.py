# apps/api/services/documents/tables.py

"""Paged table reads of delimited text and saved result lists.

Runs inside the document worker, so parsing a large upload can't block the API
process, and uses the standard library only.
"""

import csv
import io
import json
import math
import re
from collections.abc import Callable, Iterable
from itertools import islice
from typing import Any

from services.documents.reading import (
    DEFAULT_TABLE_ROWS,
    MAX_TABLE_ROWS,
    DocumentRequestError,
    ReadPage,
    name,
)
from services.documents.xlsx_model import column_names, extend_columns

_INTEGER = re.compile(r"-?(?:0|[1-9]\d{0,17})")
_DECIMAL = re.compile(r"-?(?:0|[1-9]\d*)?\.\d+(?:[eE][+-]?\d+)?")
_NODE_KEYS = frozenset({"node", "source_kind", "source_ref", "content"})
_MAX_LISTED_NAMES = 20

type ListPath = tuple[str | int, ...]


def read_delimited_table(data: bytes, *, delimiter: str, args: dict[str, Any]) -> dict[str, Any]:
    """Returns rows of CSV or TSV text as dictionaries keyed by the header row.

    Plain numbers become numbers; values with leading zeros or separators stay text.
    """
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise DocumentRequestError("The file isn't UTF-8 text. Save it as UTF-8 CSV.") from None
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        columns = column_names(next(reader, []))
        rows = (row for row in reader if any(row))
        return _page(
            columns,
            rows,
            args,
            frame=lambda row, page: _frame_row(_record(columns, row, page), page.value),
        )
    except csv.Error as exc:
        if "field limit" in str(exc):
            raise DocumentRequestError(
                f"A field is longer than the {csv.field_size_limit():,} characters "
                "table reads support."
            ) from None
        raise DocumentRequestError(f"The file isn't valid delimited text: {exc}") from None


def read_saved_list(data: bytes, args: dict[str, Any]) -> dict[str, Any]:
    """Returns one list of a JSON file as rows.

    Only a retained tool result keeps the untrusted-content nodes its source tool
    framed. Any other JSON is framed as File text, including node-shaped objects.
    """
    try:
        value = json.loads(data, parse_float=_finite_float, parse_constant=_refuse_constant)
    except ValueError as exc:
        raise DocumentRequestError(f"The file isn't valid JSON: {exc}") from None
    names = result_list_names(value)
    selected = args.get("list_name")
    if selected is None:
        if len(names) != 1:
            raise DocumentRequestError(
                f"Pass list_name. The lists in this file are: {_listed(names)}."
            )
        selected = names[0]
    items = list_at(value, selected)
    if items is None:
        raise DocumentRequestError(
            f"The file has no list {name(selected)!r}. Its lists are: {_listed(names)}."
        )
    retained = args.get("retained") is True
    return {"list_name": selected, **_read_records(items, args, retained=retained)}


def result_list_names(result: Any) -> list[str]:
    """Returns the names a preview of this result uses in `lists`."""
    return [list_name(path) for path in result_list_paths(result, None)]


def list_name(path: ListPath) -> str:
    """Returns the dotted name of a list path, or `$` for the root."""
    return ".".join(map(str, path)) or "$"


def result_list_paths(result: Any, list_path: str | None) -> list[ListPath]:
    """Returns the paths of the row lists in a structured result.

    A selected dotted path may use `*` to fan out over a list.
    """
    paths: list[ListPath] = []
    _visit(result, (), tuple(list_path.split(".")) if list_path is not None else None, paths)
    return paths


def _visit(
    value: Any, path: ListPath, pattern: tuple[str, ...] | None, paths: list[ListPath]
) -> None:
    if pattern:
        _visit_pattern(value, path, pattern, paths)
    elif isinstance(value, list):
        if pattern is None and _is_account_fan_out(value):
            for index, item in enumerate(value):
                _visit(item, (*path, index), None, paths)
        else:
            paths.append(path)
    elif isinstance(value, dict) and pattern is None:
        for key, item in value.items():
            _visit(item, (*path, key), None, paths)


def _visit_pattern(
    value: Any, path: ListPath, pattern: tuple[str, ...], paths: list[ListPath]
) -> None:
    key, *rest = pattern
    if key == "*" and isinstance(value, list):
        for index, item in enumerate(value):
            _visit(item, (*path, index), tuple(rest), paths)
    elif isinstance(value, dict) and key in value:
        _visit(value[key], (*path, key), tuple(rest), paths)


def list_at(value: Any, dotted_name: str) -> list[Any] | None:
    """Returns the list at a dotted path such as `results.0.data.rows`, or None.

    Keys that contain dots can't be addressed this way.
    """
    if dotted_name != "$":
        for key in dotted_name.split("."):
            if isinstance(value, dict):
                value = value.get(key)
            elif isinstance(value, list) and key.isdigit() and int(key) < len(value):
                value = value[int(key)]
            else:
                return None
    return value if isinstance(value, list) else None


def _is_account_fan_out(value: list[Any]) -> bool:
    # Account envelopes retain errors and identity even when their row lists shrink.
    return bool(value) and all(
        isinstance(item, dict) and "status" in item and "data" in item for item in value
    )


def _read_records(items: list[Any], args: dict[str, Any], *, retained: bool) -> dict[str, Any]:
    offset = int(args.get("offset") or 0)
    limit = min(int(args.get("limit") or DEFAULT_TABLE_ROWS), MAX_TABLE_ROWS)
    columns: list[str] = []
    for item in islice(items, offset, offset + limit):
        for key in _keys(item) if isinstance(item, dict) else ("value",):
            if key not in columns:
                columns.append(key)
    rows = (item if isinstance(item, dict) else {"value": item} for item in items)
    return _page(columns, rows, args, frame=lambda row, page: _frame_json(row, page, retained))


def _page(
    columns: list[str],
    rows: Iterable[Any],
    args: dict[str, Any],
    *,
    frame: Callable[[Any, ReadPage], dict[str, Any]],
) -> dict[str, Any]:
    page = ReadPage(args)
    page.reserve(columns, too_large="The table has more columns than one read page can hold.")
    offset = int(args.get("offset") or 0)
    limit = min(int(args.get("limit") or DEFAULT_TABLE_ROWS), MAX_TABLE_ROWS)
    selected: list[dict[str, Any]] = []
    total = 0
    next_offset = None
    for index, row in enumerate(rows):
        total += 1
        if index < offset or next_offset is not None or len(selected) >= limit:
            continue
        framed = frame(row, page)
        too_large = f"Row {index} is larger than one read page. Pass offset {index + 1} to skip it."
        if not page.add(framed, first=not selected, too_large=too_large):
            next_offset = index
            continue
        selected.append(framed)
    end = offset + len(selected)
    if next_offset is None and end < total:
        next_offset = end
    result: dict[str, Any] = {"columns": columns, "rows": selected, "total_rows": total}
    if next_offset is not None:
        result["next_offset"] = next_offset
    return result


def _record(columns: list[str], row: list[str], page: ReadPage) -> dict[str, Any]:
    """Returns a page row as a record, naming any columns past the header."""
    if len(row) > len(columns):
        columns[:] = extend_columns(columns, len(row) - len(columns), page)
    return {column: _number_or_text(value) for column, value in zip(columns, row, strict=False)}


def _frame_row(row: dict[str, Any], frame_value: Callable[[Any], Any]) -> dict[str, Any]:
    return {key: frame_value(value) for key, value in row.items()}


def _number_or_text(value: str) -> Any:
    text = value.strip()
    if not text:
        return None
    if _INTEGER.fullmatch(text):
        return int(text)
    if _DECIMAL.fullmatch(text) and math.isfinite(number := float(text)):
        return number
    return value


def _frame_json(value: Any, page: ReadPage, retained: bool) -> Any:
    """Frames plain strings anywhere in a JSON value, keeping valid nodes of a retained result."""
    if isinstance(value, dict):
        if retained and _is_node(value):
            return value
        return {key: _frame_json(item, page, retained) for key, item in _keys(value).items()}
    if isinstance(value, list):
        return [_frame_json(item, page, retained) for item in value]
    return page.value(value)


def _keys(value: dict[str, Any]) -> dict[str, Any]:
    """Returns an object keyed by capped names, refusing keys the cap can't tell apart."""
    keyed: dict[str, Any] = {}
    for key, item in value.items():
        capped = name(key)
        if capped in keyed:
            raise DocumentRequestError(
                f"Two keys start with the same {len(capped)} characters, so they can't be "
                "told apart. Shorten the keys."
            )
        keyed[capped] = item
    return keyed


def _is_node(value: dict[str, Any]) -> bool:
    return (
        value.keys() == _NODE_KEYS
        and value["node"] == "praxis_untrusted"
        and all(isinstance(value[key], str) for key in _NODE_KEYS)
    )


def _finite_float(text: str) -> float:
    number = float(text)
    if not math.isfinite(number):
        raise ValueError(f"the number {text[:40]} is too large")
    return number


def _refuse_constant(constant: str) -> Any:
    raise ValueError(f"{constant} isn't a supported number")


def _listed(names: list[str]) -> str:
    return ", ".join(name(item) for item in names[:_MAX_LISTED_NAMES]) or "none"
