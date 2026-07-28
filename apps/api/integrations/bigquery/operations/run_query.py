# apps/api/integrations/bigquery/operations/run_query.py

"""Authorize and run one bounded GoogleSQL query through BigQuery dry-run metadata."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

from pydantic_ai import ModelRetry

MAX_AUTHORIZED_REFERENCES = 49


class BigQueryQueryClient(Protocol):
    async def post(
        self,
        path: str,
        *,
        operation: str,
        json: dict[str, Any],
        request_timeout: float | None = None,
    ) -> Any: ...


@dataclass(frozen=True)
class AllowedDataset:
    project_id: str
    dataset_id: str
    location: str


async def run_query(
    client: BigQueryQueryClient,
    *,
    query: str,
    billing_project_id: str,
    allowed_datasets: Mapping[tuple[str, str], AllowedDataset],
    labels: Mapping[str, str],
    request_id: str,
    max_bytes_billed: int,
    max_rows: int,
    max_result_chars: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    dry_run = await client.post(
        f"projects/{quote(billing_project_id, safe='')}/jobs",
        operation="dry_run_query",
        json={
            "configuration": {
                "dryRun": True,
                "query": {
                    "query": query,
                    "useLegacySql": False,
                },
            }
        },
    )
    query_statistics = _query_statistics(dry_run)
    statement_type = str(query_statistics.get("statementType", "")).upper()
    if statement_type != "SELECT":
        raise ModelRetry(
            "bigquery_run_query accepts one GoogleSQL SELECT statement. "
            f"BigQuery classified this query as {statement_type or 'unknown'}."
        )

    routines = _referenced_routines(query_statistics)
    if routines:
        raise ModelRetry(
            "bigquery_run_query does not allow persistent routines because some "
            "BigQuery routines can invoke external services. Rewrite the query "
            "using tables and built-in GoogleSQL functions only."
        )

    references = _referenced_tables(query_statistics)
    if len(references) > MAX_AUTHORIZED_REFERENCES:
        raise ModelRetry(
            "BigQuery reported 50 or more referenced tables, so the complete "
            "authorization set cannot be verified. Narrow the query to fewer tables."
        )
    outside_context = [
        f"{project_id}.{dataset_id}.{table_id}"
        for project_id, dataset_id, table_id in references
        if (project_id, dataset_id) not in allowed_datasets
    ]
    if outside_context:
        raise ModelRetry(
            "The query references tables outside the active context: "
            + ", ".join(sorted(outside_context))
            + ". Ask the user to change the active context or revise the query."
        )

    estimated_bytes = _nonnegative_int(query_statistics.get("totalBytesProcessed"))
    if estimated_bytes is None:
        raise ModelRetry("BigQuery did not return a dry-run byte estimate. Revise the query.")
    if estimated_bytes > max_bytes_billed:
        raise ModelRetry(
            f"BigQuery estimates {estimated_bytes} bytes, above the "
            f"{max_bytes_billed}-byte limit. Narrow the query or add a partition filter."
        )

    location = _query_location(references, allowed_datasets)
    response = await client.post(
        f"projects/{quote(billing_project_id, safe='')}/queries",
        operation="run_query",
        json={
            "query": query,
            "useLegacySql": False,
            "useQueryCache": True,
            "maximumBytesBilled": str(max_bytes_billed),
            "maxResults": max_rows + 1,
            "timeoutMs": timeout_seconds * 1000,
            "jobTimeoutMs": str(timeout_seconds * 1000),
            "location": location,
            "labels": dict(labels),
            "requestId": request_id,
        },
        request_timeout=timeout_seconds + 5,
    )
    _raise_query_errors(response)
    if response.get("jobComplete") is not True:
        raise ModelRetry(
            f"The BigQuery job did not complete within {timeout_seconds} seconds. "
            "Narrow the query and try again."
        )
    return _query_result(
        response,
        max_rows=max_rows,
        max_result_chars=max_result_chars,
    )


def _query_statistics(payload: Any) -> dict[str, Any]:
    statistics = payload.get("statistics") if isinstance(payload, dict) else None
    query = statistics.get("query") if isinstance(statistics, dict) else None
    if not isinstance(query, dict):
        raise ModelRetry("BigQuery returned incomplete dry-run statistics. Revise the query.")
    return query


def _referenced_tables(statistics: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    raw_references = statistics.get("referencedTables")
    if raw_references is None:
        return []
    if not isinstance(raw_references, list):
        raise ModelRetry("BigQuery returned invalid referenced-table metadata. Revise the query.")
    references: list[tuple[str, str, str]] = []
    for item in raw_references:
        if not isinstance(item, dict):
            raise ModelRetry(
                "BigQuery returned invalid referenced-table metadata. Revise the query."
            )
        project_id = str(item.get("projectId", "")).strip()
        dataset_id = str(item.get("datasetId", "")).strip()
        table_id = str(item.get("tableId", "")).strip()
        if not project_id or not dataset_id or not table_id:
            raise ModelRetry(
                "BigQuery returned incomplete referenced-table metadata. Revise the query."
            )
        references.append((project_id, dataset_id, table_id))
    return references


def _referenced_routines(statistics: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    raw_routines = statistics.get("referencedRoutines")
    if raw_routines is None:
        return []
    if not isinstance(raw_routines, list):
        raise ModelRetry("BigQuery returned invalid referenced-routine metadata. Revise the query.")
    routines: list[tuple[str, str, str]] = []
    for item in raw_routines:
        if not isinstance(item, dict):
            raise ModelRetry(
                "BigQuery returned invalid referenced-routine metadata. Revise the query."
            )
        project_id = str(item.get("projectId", "")).strip()
        dataset_id = str(item.get("datasetId", "")).strip()
        routine_id = str(item.get("routineId", "")).strip()
        if not project_id or not dataset_id or not routine_id:
            raise ModelRetry(
                "BigQuery returned incomplete referenced-routine metadata. Revise the query."
            )
        routines.append((project_id, dataset_id, routine_id))
    return routines


def _query_location(
    references: list[tuple[str, str, str]],
    allowed_datasets: Mapping[tuple[str, str], AllowedDataset],
) -> str:
    datasets = (
        [allowed_datasets[(project_id, dataset_id)] for project_id, dataset_id, _ in references]
        if references
        else list(allowed_datasets.values())
    )
    locations = {dataset.location for dataset in datasets if dataset.location}
    if len(locations) != 1:
        raise ModelRetry(
            "The query's BigQuery datasets do not resolve to one location. "
            "Ask the user to narrow the active context to datasets in one location."
        )
    return next(iter(locations))


def _raise_query_errors(payload: Any) -> None:
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if not isinstance(errors, list) or not errors:
        return
    for item in errors:
        message = str(item.get("message", "")).strip() if isinstance(item, dict) else ""
        if message:
            raise ModelRetry(message)
    raise ModelRetry("BigQuery reported a query error. Revise the query.")


def _query_result(
    payload: dict[str, Any],
    *,
    max_rows: int,
    max_result_chars: int,
) -> dict[str, Any]:
    schema = payload.get("schema")
    raw_fields = schema.get("fields") if isinstance(schema, dict) else None
    column_names = _unique_column_names(raw_fields if isinstance(raw_fields, list) else [])
    raw_rows = payload.get("rows")
    rows = raw_rows if isinstance(raw_rows, list) else []
    total_rows = _nonnegative_int(payload.get("totalRows"))
    total_rows = total_rows if total_rows is not None else len(rows)
    truncated = len(rows) > max_rows or total_rows > max_rows or bool(payload.get("pageToken"))
    result: dict[str, Any] = {
        "rows": [],
        "total_rows": total_rows,
        "truncated": truncated,
        "total_bytes_processed": _nonnegative_int(payload.get("totalBytesProcessed")) or 0,
        "cache_hit": bool(payload.get("cacheHit")),
    }
    bounded_rows: list[dict[str, str | None]] = []
    for raw_row in rows[:max_rows]:
        cells = raw_row.get("f") if isinstance(raw_row, dict) else None
        values = cells if isinstance(cells, list) else []
        row = {
            column_name: (
                _cell_text(cell.get("v"))
                if isinstance(cell, dict) and cell.get("v") is not None
                else None
            )
            for column_name, cell in zip(column_names, values, strict=False)
        }
        candidate = {**result, "rows": [*bounded_rows, row]}
        if _serialized_chars(candidate) > max_result_chars:
            result["truncated"] = True
            break
        bounded_rows.append(row)
    result["rows"] = bounded_rows
    return result


def _unique_column_names(fields: list[Any]) -> list[str]:
    names: list[str] = []
    counts: dict[str, int] = {}
    for index, field in enumerate(fields):
        raw_name = str(field.get("name", "")).strip() if isinstance(field, dict) else ""
        name = raw_name or f"column_{index + 1}"
        counts[name] = counts.get(name, 0) + 1
        names.append(name if counts[name] == 1 else f"{name}_{counts[name]}")
    return names


def _cell_text(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return str(value)


def _serialized_chars(value: object) -> int:
    return len(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str))


def _nonnegative_int(value: Any) -> int | None:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None
