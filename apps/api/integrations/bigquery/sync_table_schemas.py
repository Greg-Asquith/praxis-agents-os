# apps/api/integrations/bigquery/sync_table_schemas.py

"""Synchronize enabled BigQuery dataset schemas into the local cache."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationNotFoundError, IntegrationValidationError
from core.settings import settings
from models.integration_table_schema import IntegrationTableSchema
from models.integrations import ExternalCredential, IntegrationConnection, IntegrationResource
from models.jobs import Job
from services.integrations.credentials import (
    GoogleServiceAccountTokenProvider,
    parse_google_service_account_json,
)
from services.jobs.registry import job_handler
from services.secrets import resolve_secret
from services.secrets.domain import SecretReference

from .client import BigQueryClient
from .discover_resources import BIGQUERY_SCOPE
from .settings import (
    BIGQUERY_TABLE_LIST_PAGE_SIZE,
    bigquery_settings,
)

SYNC_TABLE_SCHEMAS_KIND = "integrations.sync_table_schemas"
_TABLE_TYPES = {
    "TABLE": "table",
    "VIEW": "view",
    "MATERIALIZED_VIEW": "materialized_view",
    "EXTERNAL": "external",
}


class BigQuerySchemaClient(Protocol):
    async def get(
        self,
        path: str,
        *,
        operation: str,
        params: dict[str, Any] | None = None,
    ) -> Any: ...


@dataclass(frozen=True)
class _CachedTable:
    table_external_id: str
    table_type: str
    description: str | None
    schema_fields: list[dict[str, object]]
    partitioning: dict[str, object]
    clustering_fields: list[str]
    row_count: int | None
    size_bytes: int | None
    provider_last_modified_at: datetime | None


@job_handler(
    kind=SYNC_TABLE_SCHEMAS_KIND,
    timeout=settings.INTEGRATIONS_DISCOVERY_TIMEOUT_SECONDS,
)
async def sync_table_schemas_handler(db: AsyncSession, job: Job) -> None:
    """Run one provider-owned metadata synchronization job."""
    if job.subject_type != "integration_connection" or job.subject_id is None:
        raise ValueError("Integration table schema sync requires a connection subject")
    await sync_bigquery_table_schemas(db, connection_id=job.subject_id)


async def sync_bigquery_table_schemas(
    db: AsyncSession,
    *,
    connection_id: UUID,
    client: BigQuerySchemaClient | None = None,
) -> None:
    """Reconcile cached schemas for every currently enabled dataset."""
    connection = await db.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.id == connection_id,
            IntegrationConnection.deleted.is_(False),
        )
    )
    if connection is None:
        return
    if connection.provider_key != "bigquery":
        raise IntegrationValidationError(
            "Table schema sync requires a BigQuery connection",
            provider_key=connection.provider_key,
            connection_id=str(connection.id),
            operation="sync_table_schemas",
        )

    resources = list(
        (
            await db.scalars(
                select(IntegrationResource)
                .where(
                    IntegrationResource.connection_id == connection.id,
                    IntegrationResource.resource_type == "bigquery_dataset",
                    IntegrationResource.enabled.is_(True),
                    IntegrationResource.availability == "available",
                    IntegrationResource.deleted.is_(False),
                )
                .order_by(IntegrationResource.external_id)
            )
        ).all()
    )
    schema_client = client
    now = datetime.now(UTC)
    truncated_datasets: list[str] = []
    for resource in resources:
        if schema_client is None:
            schema_client = await _build_client(db, connection)
        project_id, dataset_id = _dataset_coordinates(resource)
        tables, truncated = await _fetch_tables(
            schema_client,
            project_id=project_id,
            dataset_id=dataset_id,
            max_tables=bigquery_settings.BIGQUERY_SCHEMA_SYNC_MAX_TABLES,
        )
        await _reconcile_tables(
            db,
            resource=resource,
            tables=tables,
            now=now,
            complete=not truncated,
        )
        if truncated:
            truncated_datasets.append(resource.external_id)

    provider_metadata = dict(connection.provider_metadata or {})
    provider_metadata["table_schema_sync"] = {
        "last_synced_at": now.isoformat(),
        "max_tables_per_dataset": bigquery_settings.BIGQUERY_SCHEMA_SYNC_MAX_TABLES,
        "truncated_datasets": truncated_datasets,
    }
    connection.provider_metadata = provider_metadata
    await db.flush()


async def _build_client(
    db: AsyncSession,
    connection: IntegrationConnection,
) -> BigQueryClient:
    credential = await db.get(ExternalCredential, connection.credential_id)
    if credential is None or credential.deleted:
        raise IntegrationNotFoundError(
            "Integration credential not found",
            provider_key="bigquery",
            connection_id=str(connection.id),
            operation="sync_table_schemas",
        )
    if credential.auth_mode != "service_account":
        raise IntegrationValidationError(
            "BigQuery requires a service-account credential",
            provider_key="bigquery",
            connection_id=str(connection.id),
            operation="sync_table_schemas",
        )
    raw = await resolve_secret(
        db,
        SecretReference(
            provider=credential.secret_provider or "",
            name=credential.secret_name or "",
            version=credential.secret_version or "",
        ),
        workspace_id=connection.owner_workspace_id,
        actor_id=connection.connected_by_user_id,
    )
    token_provider = GoogleServiceAccountTokenProvider(
        parse_google_service_account_json(raw, provider_key="bigquery"),
        provider_key="bigquery",
        scope=BIGQUERY_SCOPE,
    )
    return BigQueryClient(token_provider.access_token)


def _dataset_coordinates(resource: IntegrationResource) -> tuple[str, str]:
    metadata = resource.permissions_metadata or {}
    project_id = str(metadata.get("project_id", "")).strip()
    dataset_id = str(metadata.get("dataset_id", "")).strip()
    if not project_id or not dataset_id:
        raise IntegrationValidationError(
            "BigQuery dataset is missing routing metadata; refresh its resources",
            provider_key="bigquery",
            connection_id=str(resource.connection_id),
            operation="sync_table_schemas",
        )
    return project_id, dataset_id


async def _fetch_tables(
    client: BigQuerySchemaClient,
    *,
    project_id: str,
    dataset_id: str,
    max_tables: int,
) -> tuple[list[_CachedTable], bool]:
    table_refs, truncated = await _list_table_references(
        client,
        project_id=project_id,
        dataset_id=dataset_id,
        max_tables=max_tables,
    )
    tables: list[_CachedTable] = []
    for table_id, listed_type in table_refs:
        path = (
            f"projects/{quote(project_id, safe='')}/datasets/"
            f"{quote(dataset_id, safe='')}/tables/{quote(table_id, safe='')}"
        )
        payload = await client.get(path, operation="get_table")
        if not isinstance(payload, dict):
            raise IntegrationValidationError(
                "BigQuery returned invalid table metadata",
                provider_key="bigquery",
                operation="sync_table_schemas",
            )
        table = _normalize_table(payload, table_id=table_id, fallback_type=listed_type)
        if table is not None:
            tables.append(table)
    return tables, truncated


async def _list_table_references(
    client: BigQuerySchemaClient,
    *,
    project_id: str,
    dataset_id: str,
    max_tables: int,
) -> tuple[list[tuple[str, str]], bool]:
    path = f"projects/{quote(project_id, safe='')}/datasets/{quote(dataset_id, safe='')}/tables"
    results: list[tuple[str, str]] = []
    page_token: str | None = None
    seen_tokens: set[str] = set()
    while len(results) < max_tables:
        params: dict[str, Any] = {
            "maxResults": min(BIGQUERY_TABLE_LIST_PAGE_SIZE, max_tables - len(results))
        }
        if page_token is not None:
            params["pageToken"] = page_token
        payload = await client.get(path, operation="list_tables", params=params)
        if not isinstance(payload, dict):
            raise IntegrationValidationError(
                "BigQuery returned an invalid table list",
                provider_key="bigquery",
                operation="sync_table_schemas",
            )
        items = payload.get("tables")
        if isinstance(items, list):
            for item in items:
                reference = item.get("tableReference") if isinstance(item, dict) else None
                if not isinstance(reference, dict):
                    continue
                table_id = str(reference.get("tableId", "")).strip()
                if table_id:
                    results.append((table_id, str(item.get("type", "")).strip()))
                    if len(results) == max_tables:
                        break
        next_token = str(payload.get("nextPageToken", "")).strip()
        if not next_token:
            return results, False
        if next_token in seen_tokens:
            return results, True
        if len(results) == max_tables:
            return results, True
        seen_tokens.add(next_token)
        page_token = next_token
    return results, False


def _normalize_table(
    payload: dict[str, Any],
    *,
    table_id: str,
    fallback_type: str,
) -> _CachedTable | None:
    table_type = _TABLE_TYPES.get(str(payload.get("type") or fallback_type).upper())
    if table_type is None:
        return None
    schema = payload.get("schema")
    fields = schema.get("fields") if isinstance(schema, dict) else None
    return _CachedTable(
        table_external_id=table_id,
        table_type=table_type,
        description=_optional_text(payload.get("description")),
        schema_fields=_flatten_schema_fields(fields if isinstance(fields, list) else []),
        partitioning=_partitioning(payload),
        clustering_fields=_clustering_fields(payload),
        row_count=_optional_nonnegative_int(payload.get("numRows")),
        size_bytes=_optional_nonnegative_int(payload.get("numBytes")),
        provider_last_modified_at=_provider_timestamp(payload.get("lastModifiedTime")),
    )


def _flatten_schema_fields(
    fields: Sequence[object],
    *,
    prefix: str = "",
) -> list[dict[str, object]]:
    flattened: list[dict[str, object]] = []
    for raw_field in fields:
        if not isinstance(raw_field, dict):
            continue
        name = str(raw_field.get("name", "")).strip()
        if not name:
            continue
        dotted_name = f"{prefix}.{name}" if prefix else name
        flattened.append(
            {
                "name": dotted_name,
                "type": str(raw_field.get("type", "")).strip().upper(),
                "mode": str(raw_field.get("mode", "NULLABLE")).strip().upper() or "NULLABLE",
                "description": _optional_text(raw_field.get("description")),
            }
        )
        nested = raw_field.get("fields")
        if isinstance(nested, list):
            flattened.extend(_flatten_schema_fields(nested, prefix=dotted_name))
    return flattened


def _partitioning(payload: dict[str, Any]) -> dict[str, object]:
    require_filter = bool(payload.get("requirePartitionFilter"))
    time_partitioning = payload.get("timePartitioning")
    if isinstance(time_partitioning, dict):
        return {
            "type": str(time_partitioning.get("type", "")).strip().upper(),
            "field": str(time_partitioning.get("field", "")).strip() or None,
            "require_partition_filter": require_filter
            or bool(time_partitioning.get("requirePartitionFilter")),
        }
    range_partitioning = payload.get("rangePartitioning")
    if isinstance(range_partitioning, dict):
        return {
            "type": "RANGE",
            "field": str(range_partitioning.get("field", "")).strip() or None,
            "require_partition_filter": require_filter,
        }
    return {"require_partition_filter": True} if require_filter else {}


def _clustering_fields(payload: dict[str, Any]) -> list[str]:
    clustering = payload.get("clustering")
    fields = clustering.get("fields") if isinstance(clustering, dict) else None
    return (
        [str(field).strip() for field in fields if str(field).strip()]
        if isinstance(fields, list)
        else []
    )


def _optional_text(value: object) -> str | None:
    text_value = str(value).strip() if value is not None else ""
    return text_value or None


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _provider_timestamp(value: object) -> datetime | None:
    milliseconds = _optional_nonnegative_int(value)
    if milliseconds is None:
        return None
    try:
        return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


async def _reconcile_tables(
    db: AsyncSession,
    *,
    resource: IntegrationResource,
    tables: Sequence[_CachedTable],
    now: datetime,
    complete: bool,
) -> None:
    existing = list(
        (
            await db.scalars(
                select(IntegrationTableSchema)
                .where(IntegrationTableSchema.resource_id == resource.id)
                .with_for_update()
            )
        ).all()
    )
    by_external_id = {row.table_external_id: row for row in existing}
    seen: set[str] = set()
    for table in tables:
        seen.add(table.table_external_id)
        row = by_external_id.get(table.table_external_id)
        if row is None:
            db.add(
                IntegrationTableSchema(
                    resource_id=resource.id,
                    table_external_id=table.table_external_id,
                    table_type=table.table_type,
                    description=table.description,
                    schema_fields=table.schema_fields,
                    partitioning=table.partitioning,
                    clustering_fields=table.clustering_fields,
                    row_count=table.row_count,
                    size_bytes=table.size_bytes,
                    provider_last_modified_at=table.provider_last_modified_at,
                    availability="available",
                    first_synced_at=now,
                    last_synced_at=now,
                )
            )
            continue
        row.table_type = table.table_type
        row.description = table.description
        row.schema_fields = table.schema_fields
        row.partitioning = table.partitioning
        row.clustering_fields = table.clustering_fields
        row.row_count = table.row_count
        row.size_bytes = table.size_bytes
        row.provider_last_modified_at = table.provider_last_modified_at
        row.availability = "available"
        row.last_synced_at = now

    if complete:
        for external_id, row in by_external_id.items():
            if external_id not in seen:
                row.availability = "removed"
                row.last_synced_at = now
