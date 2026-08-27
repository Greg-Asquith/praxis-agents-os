"""BigQuery cache tools, query authorization, bounds, and audit."""

import json
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
from models.integrations import IntegrationConnection, IntegrationResource
from models.user import User
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.table_scopes.domain import TableScopeEnforcementState
from tests.factories import (
    build_external_credential,
    build_integration_connection,
    build_integration_resource,
    build_integration_table_schema,
    build_integration_table_scope_rule,
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
    assert (
        "every active BigQuery dataset in one discovery call"
        in definitions["bigquery_list_tables"].description
    )
    assert (
        "targets one table and does not repeat"
        in definitions["bigquery_get_table_schema"].description
    )
    assert "query is not repeated for each dataset" in definitions["bigquery_run_query"].description


async def test_cache_tools_scope_rows_to_active_resources(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry, cached = await _cached_table_context(db_session)
    audit = AsyncMock()
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    listed = await bigquery_list_tables(
        _ctx(db_session, (entry,), tool_name="bigquery_list_tables")
    )
    schema = await bigquery_get_table_schema(
        _ctx(db_session, (entry,), tool_name="bigquery_get_table_schema"),
        "campaign_daily",
    )
    BigQueryListTablesOutput.model_validate(listed)
    BigQueryTableSchemaOutput.model_validate(schema)
    assert listed["datasets"][0]["tables"][0]["table"] == "campaign_daily"
    assert listed["datasets"][0]["tables"][0]["description"] == cached.description
    assert schema["table"] == "`analytics.marketing.campaign_daily`"
    assert schema["requires_partition_filter"] is True
    assert schema["fields"][0]["name"] == "report_date"
    assert schema["fields"][0]["description"] == "Reporting date"
    assert listed["datasets"][0]["tables"][0]["last_synced_at"] == cached.last_synced_at.isoformat()
    assert schema["last_synced_at"] == cached.last_synced_at.isoformat()
    json.dumps(listed, allow_nan=False)
    json.dumps(schema, allow_nan=False)
    assert audit.await_count == 2
    assert {call.kwargs["operation"] for call in audit.await_args_list} == {
        "list_cached_tables",
        "get_cached_table_schema",
    }
    assert all(call.kwargs["external_ref"] is None for call in audit.await_args_list)


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
        "services.integrations.operations.record_integration_operation_audit_event",
        AsyncMock(),
    )

    with pytest.raises(ModelRetry, match="ambiguous"):
        await bigquery_get_table_schema(
            _ctx(
                db_session,
                (first, second),
                tool_name="bigquery_get_table_schema",
            ),
            "campaign_daily",
        )


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


async def test_query_rejects_persistent_routines_before_execution() -> None:
    dry_run = _dry_run()
    dry_run["statistics"]["query"]["referencedRoutines"] = [
        {
            "projectId": "analytics",
            "datasetId": "shared",
            "routineId": "remote_enrichment",
        }
    ]
    client = _QueryClient(dry_run=dry_run)

    with pytest.raises(ModelRetry, match="does not allow persistent routines"):
        await _run_operation(client)

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
    assert query_request["request_timeout"] == 65
    assert result["rows"][0]["campaign"] == "Quarterly revenue"
    assert result["row_filters_applied"] is False
    assert client.calls[0]["json"] == {
        "configuration": {
            "dryRun": True,
            "query": {
                "query": "SELECT * FROM `analytics.marketing.campaign_daily`",
                "useLegacySql": False,
            },
        }
    }
    assert "parameterMode" not in query_request["json"]
    assert "queryParameters" not in query_request["json"]


async def test_query_sends_row_filter_parameters_to_dry_run_and_execution() -> None:
    client = _QueryClient(dry_run=_dry_run())
    parameters = (
        {
            "name": "praxis_scope_0",
            "parameterType": {"type": "ARRAY", "arrayType": {"type": "STRING"}},
            "parameterValue": {"arrayValues": [{"value": "account-1"}]},
        },
    )

    result = await run_query(
        client,
        query="SELECT * FROM filtered",
        billing_project_id="analytics",
        allowed_datasets={
            ("analytics", "marketing"): AllowedDataset(
                project_id="analytics",
                dataset_id="marketing",
                location="EU",
            )
        },
        labels={},
        request_id="request-id",
        max_bytes_billed=1024,
        max_rows=10,
        max_result_chars=16_000,
        timeout_seconds=60,
        query_parameters=parameters,
        permitted_tables=frozenset({("analytics", "marketing", "campaign_daily")}),
    )

    for request in client.calls:
        query_config = (
            request["json"]["configuration"]["query"]
            if request["operation"] == "dry_run_query"
            else request["json"]
        )
        assert query_config["parameterMode"] == "NAMED"
        assert query_config["queryParameters"] == list(parameters)
    assert result["row_filters_applied"] is True


async def test_query_reports_no_filter_when_enforcement_emits_no_parameters() -> None:
    client = _QueryClient(dry_run=_dry_run())

    result = await run_query(
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
        labels={},
        request_id="request-id",
        max_bytes_billed=1024,
        max_rows=10,
        max_result_chars=16_000,
        timeout_seconds=60,
        query_parameters=(),
        permitted_tables=frozenset({("analytics", "marketing", "campaign_daily")}),
    )

    assert result["row_filters_applied"] is False


async def test_query_rejects_dry_run_reference_outside_permitted_tables() -> None:
    client = _QueryClient(dry_run=_dry_run(references=[("analytics", "marketing", "hidden_view")]))

    with pytest.raises(ModelRetry, match="unavailable while row filters are active"):
        await run_query(
            client,
            query="SELECT * FROM rewritten",
            billing_project_id="analytics",
            allowed_datasets={
                ("analytics", "marketing"): AllowedDataset(
                    project_id="analytics",
                    dataset_id="marketing",
                    location="EU",
                )
            },
            labels={},
            request_id="request-id",
            max_bytes_billed=1024,
            max_rows=10,
            max_result_chars=16_000,
            timeout_seconds=60,
            query_parameters=(),
            permitted_tables=frozenset({("analytics", "marketing", "campaign_daily")}),
        )

    assert len(client.calls) == 1


async def test_query_bounds_structured_result_characters() -> None:
    client = _QueryClient(
        dry_run=_dry_run(),
        query_response={
            "jobComplete": True,
            "schema": {"fields": [{"name": "large_value"}]},
            "rows": [{"f": [{"v": "x" * 5000}]}],
            "totalRows": "1",
            "totalBytesProcessed": "1",
            "cacheHit": False,
        },
    )

    result = await _run_operation(client, max_result_chars=1000)

    assert result["rows"] == []
    assert result["total_rows"] == 1
    assert result["truncated"] is True


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
    ctx = _ctx(object(), entries, tool_name="bigquery_run_query")
    provider_run = AsyncMock(
        return_value={
            "rows": [],
            "total_rows": 0,
            "truncated": False,
            "total_bytes_processed": 0,
            "cache_hit": False,
            "row_filters_applied": False,
        }
    )
    audit = AsyncMock()
    monkeypatch.setattr(
        "integrations.bigquery.tools.run_query.bigquery_query_client",
        AsyncMock(return_value=(object(), "billing-project")),
    )
    monkeypatch.setattr(
        "integrations.bigquery.tools.run_query.run_query",
        provider_run,
    )
    monkeypatch.setattr(
        "integrations.bigquery.tools.run_query.load_table_scope_enforcement_state",
        AsyncMock(
            return_value=TableScopeEnforcementState(
                rules=(),
                permitted_table_ids_by_resource={},
            )
        ),
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    result = await bigquery_run_query(ctx, "SELECT 1")

    BigQueryRunQueryOutput.model_validate(result)
    provider_run.assert_awaited_once()
    assert provider_run.await_args.kwargs["request_id"] == str(ctx.deps.run.id)
    assert provider_run.await_args.kwargs["billing_project_id"] == "billing-project"
    assert set(provider_run.await_args.kwargs["allowed_datasets"]) == {
        ("analytics", "marketing"),
        ("analytics", "finance"),
    }
    assert audit.await_count == 2
    assert {call.kwargs["integration_resource_id"] for call in audit.await_args_list} == {
        entry.integration_resource_id for entry in entries
    }
    assert all(call.kwargs["external_ref"] is None for call in audit.await_args_list)


async def test_query_tool_rewrites_with_fresh_rules_and_discloses_filtering(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry, cached = await _cached_table_context(db_session)
    resource = await db_session.get(IntegrationResource, cached.resource_id)
    assert resource is not None
    connection = await db_session.get(IntegrationConnection, resource.connection_id)
    assert connection is not None
    user = await db_session.get(User, connection.connected_by_user_id)
    assert user is not None
    db_session.add(
        build_integration_table_scope_rule(
            connection=connection,
            resource=resource,
            user=user,
            table_external_id="campaign_daily",
            column_name="account_id",
            allowed_values=["account-1"],
        )
    )
    await db_session.flush()
    client = _QueryClient(dry_run=_dry_run())
    monkeypatch.setattr(
        "integrations.bigquery.tools.run_query.bigquery_query_client",
        AsyncMock(return_value=(client, "analytics")),
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        AsyncMock(),
    )

    result = await bigquery_run_query(
        _ctx(db_session, (entry,), tool_name="bigquery_run_query"),
        "SELECT * FROM `analytics.marketing.campaign_daily`",
    )

    assert result["row_filters_applied"] is True
    dry_query = client.calls[0]["json"]["configuration"]["query"]
    execution_query = client.calls[1]["json"]
    assert dry_query["query"] == execution_query["query"]
    assert "UNNEST(@praxis_scope_0)" in dry_query["query"]
    assert dry_query["queryParameters"] == execution_query["queryParameters"]
    assert dry_query["queryParameters"][0]["parameterValue"] == {
        "arrayValues": [{"value": "account-1"}]
    }


@pytest.mark.parametrize(
    "schema_fields",
    [
        [{"name": "other_id", "type": "STRING", "mode": "REQUIRED"}],
        [{"name": "account_id", "type": "STRING", "mode": "REPEATED"}],
        [{"name": "account_id", "type": "FLOAT64", "mode": "REQUIRED"}],
    ],
)
async def test_query_tool_rejects_rules_that_no_longer_match_cached_columns(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    schema_fields: list[dict[str, str]],
) -> None:
    entry, cached = await _cached_table_context(db_session)
    resource = await db_session.get(IntegrationResource, cached.resource_id)
    assert resource is not None
    connection = await db_session.get(IntegrationConnection, resource.connection_id)
    assert connection is not None
    user = await db_session.get(User, connection.connected_by_user_id)
    assert user is not None
    cached.schema_fields = schema_fields
    db_session.add(
        build_integration_table_scope_rule(
            connection=connection,
            resource=resource,
            user=user,
            table_external_id="campaign_daily",
            column_name="account_id",
        )
    )
    await db_session.flush()
    query_client = AsyncMock(return_value=(object(), "analytics"))
    monkeypatch.setattr(
        "integrations.bigquery.tools.run_query.bigquery_query_client",
        query_client,
    )

    with pytest.raises(ModelRetry, match="no longer matches the cached table schema"):
        await bigquery_run_query(
            _ctx(db_session, (entry,), tool_name="bigquery_run_query"),
            "SELECT * FROM `analytics.marketing.campaign_daily`",
        )

    query_client.assert_not_awaited()


@pytest.mark.parametrize(
    ("table_type", "queried_table", "expected_message"),
    [
        ("view", "campaign_daily", "available base table"),
        ("materialized_view", "campaign_daily", "available base table"),
        ("external", "campaign_daily", "available base table"),
        ("table", "missing_table", "view or unknown table"),
    ],
)
async def test_query_tool_rejects_non_base_and_unknown_tables_when_rules_exist(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    table_type: str,
    queried_table: str,
    expected_message: str,
) -> None:
    entry, cached = await _cached_table_context(db_session)
    resource = await db_session.get(IntegrationResource, cached.resource_id)
    assert resource is not None
    connection = await db_session.get(IntegrationConnection, resource.connection_id)
    assert connection is not None
    user = await db_session.get(User, connection.connected_by_user_id)
    assert user is not None
    cached.table_type = table_type
    db_session.add(
        build_integration_table_scope_rule(
            connection=connection,
            resource=resource,
            user=user,
            table_external_id="campaign_daily",
            column_name="account_id",
        )
    )
    await db_session.flush()
    monkeypatch.setattr(
        "integrations.bigquery.tools.run_query.bigquery_query_client",
        AsyncMock(return_value=(object(), "analytics")),
    )

    with pytest.raises(ModelRetry, match=expected_message):
        await bigquery_run_query(
            _ctx(db_session, (entry,), tool_name="bigquery_run_query"),
            f"SELECT * FROM `analytics.marketing.{queried_table}`",  # noqa: S608
        )


async def _run_operation(
    client: "_QueryClient",
    *,
    max_bytes: int = 1024,
    max_rows: int = 10,
    max_result_chars: int = 16_000,
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
        max_result_chars=max_result_chars,
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

    async def post(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        json: dict,
        request_timeout: float | None = None,
    ):
        self.calls.append(
            {
                "path": path,
                "operation": operation,
                "policy": policy,
                "json": json,
                "request_timeout": request_timeout,
            }
        )
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
            },
            {
                "name": "account_id",
                "type": "STRING",
                "mode": "REQUIRED",
                "description": "Client account",
            },
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


def _ctx(db, entries, *, tool_name: str | None = None):
    return SimpleNamespace(
        deps=SimpleNamespace(
            db=db,
            active_context=ResolvedActiveContext(entries=tuple(entries)),
            workspace=SimpleNamespace(id=uuid4()),
            user=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name=tool_name,
    )
