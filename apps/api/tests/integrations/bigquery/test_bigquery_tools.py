"""BigQuery cache tools, query authorization, bounds, and audit."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry
from sqlalchemy.ext.asyncio import AsyncSession

from integrations.bigquery.operations.run_query import (
    MAX_AUTHORIZED_REFERENCES,
    AllowedDataset,
    run_query,
)
from integrations.bigquery.tools import TOOL_DEFINITIONS
from integrations.bigquery.tools.get_table_schema import bigquery_get_table_schema
from integrations.bigquery.tools.list_tables import bigquery_list_tables
from integrations.bigquery.tools.run_query import bigquery_run_query
from integrations.bigquery.tools.schemas import (
    BigQueryListTablesOutput,
    BigQueryRunQueryOutput,
    BigQueryTableSchemaOutput,
)
from models.integrations import IntegrationConnection
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from tests.factories import (
    build_external_credential,
    build_integration_connection,
    build_integration_resource,
    build_integration_table_schema,
    build_user,
    build_workspace,
)


def test_tool_contracts_are_cache_or_context_bound_read_tools() -> None:
    definitions = {definition.name: definition for definition in TOOL_DEFINITIONS}

    assert set(definitions) == {
        "bigquery_list_tables",
        "bigquery_get_table_schema",
        "bigquery_run_query",
    }
    for definition in definitions.values():
        assert definition.effect == "read"
        assert definition.default_policy == "auto"
        assert definition.presentation.icon == "bigquery"
        assert definition.supports_approval is True
        assert definition.integration_binding is not None
        assert definition.integration_binding.provider_keys == frozenset({"bigquery"})
        assert definition.integration_binding.resource_types == frozenset({"bigquery_dataset"})
        assert definition.output_model is not None
        assert definition.presentation.running_label
        assert definition.presentation.completed_label
        assert definition.presentation.failed_label


async def test_cache_tools_scope_rows_to_active_resources(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry, cached = await _cached_table_context(db_session)
    audit = AsyncMock()
    monkeypatch.setattr(
        "integrations.bigquery.tools.utils.record_integration_operation_audit_event",
        audit,
    )
    ctx = _ctx(db_session, (entry,))

    listed = await bigquery_list_tables(ctx)
    schema = await bigquery_get_table_schema(ctx, "campaign_daily")
    BigQueryListTablesOutput.model_validate(listed)
    BigQueryTableSchemaOutput.model_validate(schema)
    assert listed["datasets"][0]["tables"][0]["table"] == "campaign_daily"
    assert listed["datasets"][0]["tables"][0]["description"] == cached.description
    assert schema["table"] == "`analytics.marketing.campaign_daily`"
    assert schema["requires_partition_filter"] is True
    assert schema["fields"][0]["name"] == "report_date"
    assert schema["fields"][0]["description"] == "Reporting date"
    assert audit.await_count == 2
    assert {call.kwargs["operation"] for call in audit.await_args_list} == {
        "list_cached_tables",
        "get_cached_table_schema",
    }


async def test_get_schema_requires_qualification_when_table_name_is_ambiguous(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, _cached = await _cached_table_context(db_session)
    connection_model = await db_session.get(IntegrationConnection, first.connection_id)
    assert connection_model is not None
    second_resource = build_integration_resource(
        connection=connection_model,
        resource_type="bigquery_dataset",
        external_id="analytics.finance",
        permissions_metadata={
            "project_id": "analytics",
            "dataset_id": "finance",
            "location": "EU",
        },
    )
    db_session.add(second_resource)
    await db_session.flush()
    db_session.add(
        build_integration_table_schema(
            resource=second_resource,
            table_external_id="campaign_daily",
        )
    )
    await db_session.flush()
    second = _entry(
        resource_id=second_resource.id,
        connection_id=first.connection_id,
        external_id="analytics.finance",
    )
    monkeypatch.setattr(
        "integrations.bigquery.tools.utils.record_integration_operation_audit_event",
        AsyncMock(),
    )

    with pytest.raises(ModelRetry, match="ambiguous"):
        await bigquery_get_table_schema(_ctx(db_session, (first, second)), "campaign_daily")


@pytest.mark.parametrize("statement_type", ["INSERT", "CREATE_TABLE", "SCRIPT"])
async def test_query_rejects_non_select_statement_types(statement_type: str) -> None:
    client = _QueryClient(dry_run=_dry_run(statement_type=statement_type))

    with pytest.raises(ModelRetry, match="accepts one GoogleSQL SELECT"):
        await _run_operation(client)

    assert len(client.calls) == 1


async def test_query_rejects_out_of_context_tables() -> None:
    client = _QueryClient(dry_run=_dry_run(references=[("other", "private", "secrets")]))

    with pytest.raises(ModelRetry, match="outside the active context"):
        await _run_operation(client)

    assert len(client.calls) == 1


async def test_query_fails_closed_at_documented_reference_limit() -> None:
    references = [
        ("analytics", "marketing", f"table_{index}")
        for index in range(MAX_AUTHORIZED_REFERENCES + 1)
    ]
    client = _QueryClient(dry_run=_dry_run(references=references))

    with pytest.raises(ModelRetry, match="complete authorization set cannot be verified"):
        await _run_operation(client)

    assert len(client.calls) == 1


async def test_query_rejects_dry_run_above_byte_cap() -> None:
    client = _QueryClient(dry_run=_dry_run(total_bytes=1025))

    with pytest.raises(ModelRetry, match="1025 bytes"):
        await _run_operation(client, max_bytes=1024)

    assert len(client.calls) == 1


async def test_query_stamps_labels_location_and_caps_rows() -> None:
    client = _QueryClient(
        dry_run=_dry_run(total_bytes=512),
        query_response={
            "jobComplete": True,
            "jobReference": {"jobId": "job-123", "location": "EU"},
            "schema": {"fields": [{"name": "campaign"}, {"name": "revenue"}]},
            "rows": [
                {"f": [{"v": "Quarterly revenue"}, {"v": "42"}]},
                {"f": [{"v": "second"}, {"v": "21"}]},
            ],
            "totalRows": "2",
            "totalBytesProcessed": "512",
            "cacheHit": True,
            "pageToken": "more",
        },
    )

    result = await _run_operation(client, max_rows=1)
    BigQueryRunQueryOutput.model_validate(result)

    assert result["total_rows"] == 2
    assert result["truncated"] is True
    assert len(result["rows"]) == 1
    query_request = client.calls[1]
    assert query_request["path"] == "projects/analytics/queries"
    assert query_request["json"]["location"] == "EU"
    assert query_request["json"]["maximumBytesBilled"] == "1024"
    assert query_request["json"]["maxResults"] == 2
    assert query_request["json"]["labels"] == {
        "praxis_workspace": "workspace",
        "praxis_agent": "agent",
        "praxis_run": "run",
    }
    assert query_request["json"]["requestId"] == "00000000-0000-0000-0000-000000000089"
    assert result["rows"][0]["campaign"] == "Quarterly revenue"


async def test_query_tool_rejects_multiple_bigquery_connections_before_provider_io() -> None:
    entries = (
        _entry(connection_id=uuid4(), external_id="analytics.marketing"),
        _entry(connection_id=uuid4(), external_id="analytics.finance"),
    )

    with pytest.raises(ModelRetry, match="multiple connections"):
        await bigquery_run_query(_ctx(object(), entries), "SELECT 1")


async def test_query_tool_audits_each_active_dataset_and_stamps_runtime_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_id = uuid4()
    entries = (
        _entry(connection_id=connection_id, external_id="analytics.marketing"),
        _entry(connection_id=connection_id, external_id="analytics.finance"),
    )
    ctx = _ctx(object(), entries)
    provider_run = AsyncMock(
        return_value={
            "rows": [],
            "total_rows": 0,
            "truncated": False,
            "total_bytes_processed": 0,
            "cache_hit": False,
        }
    )
    audit = AsyncMock()
    monkeypatch.setattr(
        "integrations.bigquery.tools.run_query.bigquery_client",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr(
        "integrations.bigquery.tools.run_query.run_query",
        provider_run,
    )
    monkeypatch.setattr(
        "integrations.bigquery.tools.utils.record_integration_operation_audit_event",
        audit,
    )

    result = await bigquery_run_query(ctx, "SELECT 1")

    BigQueryRunQueryOutput.model_validate(result)
    assert provider_run.await_args.kwargs["request_id"] == str(ctx.deps.run.id)
    assert set(provider_run.await_args.kwargs["allowed_datasets"]) == {
        ("analytics", "marketing"),
        ("analytics", "finance"),
    }
    assert audit.await_count == 2
    assert {call.kwargs["integration_resource_id"] for call in audit.await_args_list} == {
        entry.integration_resource_id for entry in entries
    }


async def _run_operation(
    client: "_QueryClient",
    *,
    max_bytes: int = 1024,
    max_rows: int = 10,
):
    return await run_query(
        client,
        query="SELECT * FROM `analytics.marketing.campaign_daily`",
        billing_project_id="analytics",
        allowed_datasets={
            ("analytics", "marketing"): AllowedDataset(
                project_id="analytics",
                dataset_id="marketing",
                location="EU",
            )
        },
        labels={
            "praxis_workspace": "workspace",
            "praxis_agent": "agent",
            "praxis_run": "run",
        },
        request_id="00000000-0000-0000-0000-000000000089",
        max_bytes_billed=max_bytes,
        max_rows=max_rows,
        timeout_seconds=60,
    )


def _dry_run(
    *,
    statement_type: str = "SELECT",
    references: list[tuple[str, str, str]] | None = None,
    total_bytes: int = 100,
):
    resolved = references or [("analytics", "marketing", "campaign_daily")]
    return {
        "statistics": {
            "query": {
                "statementType": statement_type,
                "referencedTables": [
                    {
                        "projectId": project_id,
                        "datasetId": dataset_id,
                        "tableId": table_id,
                    }
                    for project_id, dataset_id, table_id in resolved
                ],
                "totalBytesProcessed": str(total_bytes),
            }
        }
    }


class _QueryClient:
    def __init__(
        self,
        *,
        dry_run: dict,
        query_response: dict | None = None,
    ) -> None:
        self.responses = iter(
            [
                dry_run,
                query_response
                or {
                    "jobComplete": True,
                    "schema": {"fields": []},
                    "rows": [],
                    "totalRows": "0",
                    "totalBytesProcessed": "0",
                    "cacheHit": False,
                },
            ]
        )
        self.calls: list[dict] = []

    async def post(self, path: str, *, operation: str, json: dict):
        self.calls.append({"path": path, "operation": operation, "json": json})
        return next(self.responses)


async def _cached_table_context(db: AsyncSession):
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
    )
    db.add(connection)
    await db.flush()
    resource = build_integration_resource(
        connection=connection,
        resource_type="bigquery_dataset",
        external_id="analytics.marketing",
        display_name="Marketing",
        permissions_metadata={
            "project_id": "analytics",
            "dataset_id": "marketing",
            "location": "EU",
        },
    )
    db.add(resource)
    await db.flush()
    cached = build_integration_table_schema(
        resource=resource,
        table_external_id="campaign_daily",
        description="Daily campaign performance",
        schema_fields=[
            {
                "name": "report_date",
                "type": "DATE",
                "mode": "REQUIRED",
                "description": "Reporting date",
            }
        ],
        partitioning={
            "type": "DAY",
            "field": "report_date",
            "require_partition_filter": True,
        },
        clustering_fields=["campaign_id"],
        row_count=120,
        size_bytes=4096,
        first_synced_at=datetime.now(UTC),
        last_synced_at=datetime.now(UTC),
    )
    db.add(cached)
    await db.flush()
    return (
        _entry(
            resource_id=resource.id,
            connection_id=connection.id,
            external_id=resource.external_id,
        ),
        cached,
    )


def _entry(
    *,
    resource_id=None,
    connection_id=None,
    external_id: str = "analytics.marketing",
):
    project_id, dataset_id = external_id.split(".", maxsplit=1)
    return ResolvedContextEntry(
        integration_resource_id=resource_id or uuid4(),
        provider_key="bigquery",
        resource_type="bigquery_dataset",
        external_id=external_id,
        display_name=external_id,
        connection_id=connection_id or uuid4(),
        connection_label="Warehouse",
        connection_status="active",
        write_allowed=False,
        permissions_metadata={
            "project_id": project_id,
            "dataset_id": dataset_id,
            "location": "EU",
        },
    )


def _ctx(db, entries):
    return SimpleNamespace(
        deps=SimpleNamespace(
            db=db,
            active_context=ResolvedActiveContext(entries=tuple(entries)),
            workspace=SimpleNamespace(id=uuid4()),
            user=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        )
    )
