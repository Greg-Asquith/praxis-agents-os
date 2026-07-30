"""BigQuery schema-cache synchronization behavior."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from integrations.bigquery.settings import bigquery_settings
from integrations.bigquery.sync_table_schemas import (
    SYNC_TABLE_SCHEMAS_KIND,
    sync_bigquery_table_schemas,
    sync_table_schemas_handler,
)
from models.integration_table_schema import IntegrationTableSchema
from models.integrations import ExternalCredential
from models.jobs import Job
from tests.factories import (
    build_external_credential,
    build_integration_connection,
    build_integration_resource,
    build_integration_table_schema,
    build_job,
    build_user,
    build_workspace,
)


async def _bigquery_connection(db: AsyncSession):
    user = build_user()
    workspace = build_workspace()
    credential = build_external_credential(
        provider_key="bigquery",
        auth_mode="service_account",
        access_token_encrypted=None,
        secret_provider="local",  # noqa: S106 - inert test reference metadata
        secret_name="test/bigquery",  # noqa: S106 - inert test reference metadata
        secret_version="00000001",  # noqa: S106 - inert test reference metadata
    )
    db.add_all([user, workspace, credential])
    await db.flush()
    connection = build_integration_connection(
        credential=credential,
        user=user,
        workspace=workspace,
        status="active",
        provider_metadata={"preserved": True},
    )
    db.add(connection)
    await db.flush()
    return connection


def _dataset(connection, *, external_id: str, enabled: bool = True):
    project_id, dataset_id = external_id.split(".", maxsplit=1)
    return build_integration_resource(
        connection=connection,
        resource_type="bigquery_dataset",
        external_id=external_id,
        enabled=enabled,
        permissions_metadata={
            "project_id": project_id,
            "dataset_id": dataset_id,
            "location": "EU",
        },
    )


async def test_sync_reconciles_schema_details_and_marks_missing_tables_removed(
    db_session: AsyncSession,
) -> None:
    connection = await _bigquery_connection(db_session)
    resource = _dataset(connection, external_id="analytics.marketing")
    db_session.add(resource)
    await db_session.flush()
    first_client = _SchemaClient(
        list_responses=[
            {
                "tables": [
                    {
                        "tableReference": {"tableId": "campaign_daily"},
                        "type": "TABLE",
                    },
                    {
                        "tableReference": {"tableId": "active_campaigns"},
                        "type": "VIEW",
                    },
                ]
            }
        ],
        table_responses={
            "campaign_daily": {
                "type": "TABLE",
                "description": "Daily campaign performance",
                "schema": {
                    "fields": [
                        {"name": "campaign_id", "type": "STRING", "mode": "REQUIRED"},
                        {
                            "name": "metrics",
                            "type": "RECORD",
                            "fields": [
                                {
                                    "name": "clicks",
                                    "type": "INTEGER",
                                    "description": "Recorded clicks",
                                }
                            ],
                        },
                    ]
                },
                "timePartitioning": {"type": "DAY", "field": "report_date"},
                "requirePartitionFilter": True,
                "clustering": {"fields": ["campaign_id"]},
                "numRows": "120",
                "numBytes": "4096",
                "lastModifiedTime": "1720000000000",
            },
            "active_campaigns": {
                "type": "VIEW",
                "schema": {"fields": [{"name": "campaign_id", "type": "STRING"}]},
            },
        },
    )

    await sync_bigquery_table_schemas(
        db_session,
        connection_id=connection.id,
        client=first_client,
    )
    rows = list(
        (
            await db_session.scalars(
                select(IntegrationTableSchema)
                .where(IntegrationTableSchema.resource_id == resource.id)
                .order_by(IntegrationTableSchema.table_external_id)
            )
        ).all()
    )
    assert [row.table_external_id for row in rows] == [
        "active_campaigns",
        "campaign_daily",
    ]
    campaign = rows[1]
    campaign_id = campaign.id
    first_synced_at = campaign.first_synced_at
    assert campaign.schema_fields == [
        {
            "name": "campaign_id",
            "type": "STRING",
            "mode": "REQUIRED",
            "description": None,
        },
        {
            "name": "metrics",
            "type": "RECORD",
            "mode": "NULLABLE",
            "description": None,
        },
        {
            "name": "metrics.clicks",
            "type": "INTEGER",
            "mode": "NULLABLE",
            "description": "Recorded clicks",
        },
    ]
    assert campaign.partitioning == {
        "type": "DAY",
        "field": "report_date",
        "require_partition_filter": True,
    }
    assert campaign.clustering_fields == ["campaign_id"]
    assert campaign.row_count == 120
    assert campaign.size_bytes == 4096
    assert campaign.provider_last_modified_at == datetime.fromtimestamp(1720000000, tz=UTC)

    second_client = _SchemaClient(
        list_responses=[
            {
                "tables": [
                    {
                        "tableReference": {"tableId": "campaign_daily"},
                        "type": "TABLE",
                    }
                ]
            }
        ],
        table_responses={
            "campaign_daily": {
                "type": "TABLE",
                "description": "Updated description",
                "schema": {"fields": []},
                "numRows": "121",
            }
        },
    )
    await sync_bigquery_table_schemas(
        db_session,
        connection_id=connection.id,
        client=second_client,
    )
    await db_session.refresh(campaign)
    await db_session.refresh(rows[0])
    assert campaign.id == campaign_id
    assert campaign.first_synced_at == first_synced_at
    assert campaign.description == "Updated description"
    assert campaign.row_count == 121
    assert campaign.availability == "available"
    assert rows[0].availability == "removed"
    assert (
        len(
            (
                await db_session.scalars(
                    select(IntegrationTableSchema).where(
                        IntegrationTableSchema.resource_id == resource.id
                    )
                )
            ).all()
        )
        == 2
    )


async def test_sync_is_enabled_only_and_preserves_unseen_rows_when_truncated(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bigquery_settings, "BIGQUERY_SCHEMA_SYNC_MAX_TABLES", 1)
    connection = await _bigquery_connection(db_session)
    enabled = _dataset(connection, external_id="analytics.enabled")
    disabled = _dataset(connection, external_id="analytics.disabled", enabled=False)
    db_session.add_all([enabled, disabled])
    await db_session.flush()
    old_sync_time = datetime.now(UTC) - timedelta(days=1)
    retained = build_integration_table_schema(
        resource=enabled,
        table_external_id="not_in_truncated_page",
        first_synced_at=old_sync_time,
        last_synced_at=old_sync_time,
    )
    disabled_cache = build_integration_table_schema(
        resource=disabled,
        table_external_id="disabled_table",
        first_synced_at=old_sync_time,
        last_synced_at=old_sync_time,
    )
    db_session.add_all([retained, disabled_cache])
    await db_session.flush()
    client = _SchemaClient(
        list_responses=[
            {
                "tables": [
                    {
                        "tableReference": {"tableId": "first_table"},
                        "type": "TABLE",
                    }
                ],
                "nextPageToken": "more",
            }
        ],
        table_responses={
            "first_table": {
                "type": "TABLE",
                "schema": {"fields": []},
            }
        },
    )

    await sync_bigquery_table_schemas(
        db_session,
        connection_id=connection.id,
        client=client,
    )
    await db_session.refresh(retained)
    await db_session.refresh(disabled_cache)
    await db_session.refresh(connection)

    assert retained.availability == "available"
    assert retained.last_synced_at == old_sync_time
    assert disabled_cache.last_synced_at == old_sync_time
    assert all("/datasets/enabled/" in path for path, _params in client.calls)
    assert connection.provider_metadata["preserved"] is True
    assert connection.provider_metadata["table_schema_sync"] == {
        "last_synced_at": connection.provider_metadata["table_schema_sync"]["last_synced_at"],
        "max_tables_per_dataset": 1,
        "truncated_datasets": ["analytics.enabled"],
    }


async def test_connection_sync_job_fans_out_one_deduplicated_job_per_enabled_dataset(
    db_session: AsyncSession,
) -> None:
    connection = await _bigquery_connection(db_session)
    enabled = _dataset(connection, external_id="analytics.enabled")
    disabled = _dataset(connection, external_id="analytics.disabled", enabled=False)
    db_session.add_all([enabled, disabled])
    await db_session.flush()
    coordinator = build_job(
        kind=SYNC_TABLE_SCHEMAS_KIND,
        workspace_id=connection.owner_workspace_id,
        subject_type="integration_connection",
        subject_id=connection.id,
        initiated_by_user_id=connection.connected_by_user_id,
    )

    await sync_table_schemas_handler(db_session, coordinator)
    await sync_table_schemas_handler(db_session, coordinator)

    jobs = list(
        (
            await db_session.scalars(
                select(Job).where(
                    Job.kind == SYNC_TABLE_SCHEMAS_KIND,
                    Job.subject_type == "integration_resource",
                )
            )
        ).all()
    )
    assert len(jobs) == 1
    assert jobs[0].subject_id == enabled.id
    assert jobs[0].workspace_id == connection.owner_workspace_id
    assert jobs[0].initiated_by_user_id == connection.connected_by_user_id


@pytest.mark.parametrize(
    ("status", "credential_revoked"),
    [
        ("auth_pending", False),
        ("needs_reauth", False),
        ("needs_credential", False),
        ("revoked", True),
        ("active", True),
    ],
)
async def test_sync_skips_connections_without_usable_credentials(
    db_session: AsyncSession,
    status: str,
    credential_revoked: bool,
) -> None:
    connection = await _bigquery_connection(db_session)
    connection.status = status
    resource = _dataset(connection, external_id="analytics.enabled")
    db_session.add(resource)
    await db_session.flush()
    if credential_revoked:
        credential = await db_session.get(ExternalCredential, connection.credential_id)
        assert credential is not None
        credential.revoked_at = datetime.now(UTC)
        await db_session.flush()
    client = _SchemaClient(list_responses=[], table_responses={})

    await sync_bigquery_table_schemas(
        db_session,
        connection_id=connection.id,
        client=client,
    )

    assert client.calls == []


class _SchemaClient:
    def __init__(
        self,
        *,
        list_responses: list[dict[str, Any]],
        table_responses: dict[str, dict[str, Any]],
    ) -> None:
        self._list_responses = iter(list_responses)
        self._table_responses = table_responses
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def get(
        self,
        path: str,
        *,
        operation: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append((path, params))
        if operation == "list_tables":
            return next(self._list_responses)
        assert operation == "get_table"
        return self._table_responses[path.rsplit("/", maxsplit=1)[-1]]
