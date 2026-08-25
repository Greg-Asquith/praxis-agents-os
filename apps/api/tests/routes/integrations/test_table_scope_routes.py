"""Integration table row-scope management route coverage."""

import pytest
from httpx2 import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.audit_event import AuditEvent
from models.integrations import IntegrationConnection, IntegrationResource
from models.workspace import WorkspaceRole
from tests.factories import (
    build_external_credential,
    build_integration_connection,
    build_integration_resource,
    build_integration_table_schema,
)
from tests.routes.integrations.conftest import create_identity

pytestmark = pytest.mark.asyncio


async def _bigquery_connection(
    db: AsyncSession,
    identity: dict[str, object],
) -> tuple[IntegrationConnection, IntegrationResource]:
    credential = build_external_credential(
        provider_key="bigquery",
        auth_mode="service_account",
        access_token_encrypted=None,
        secret_provider="local",  # noqa: S106 - inert test reference metadata
        secret_name="test/bigquery",  # noqa: S106 - inert test reference metadata
        secret_version="00000001",  # noqa: S106 - inert test reference metadata
    )
    connection = build_integration_connection(
        credential=credential,
        user=identity["user"],
        workspace=identity["workspace"],
        status="active",
        label="Client warehouse",
    )
    resource = build_integration_resource(
        connection=connection,
        resource_type="bigquery_dataset",
        external_id="analytics.marketing",
        display_name="Marketing",
        enabled=True,
        permissions_metadata={
            "project_id": "analytics",
            "dataset_id": "marketing",
            "location": "EU",
        },
    )
    db.add_all([credential, connection, resource])
    await db.flush()
    db.add_all(
        [
            build_integration_table_schema(
                resource=resource,
                table_external_id="campaign_daily",
                description="Daily campaign performance",
                schema_fields=[
                    {
                        "name": "account_id",
                        "type": "STRING",
                        "mode": "REQUIRED",
                        "description": "Client account",
                    },
                    {"name": "legacy_id", "type": "INTEGER", "mode": "NULLABLE"},
                    {"name": "tags", "type": "STRING", "mode": "REPEATED"},
                    {"name": "report_date", "type": "DATE", "mode": "REQUIRED"},
                ],
            ),
            build_integration_table_schema(
                resource=resource,
                table_external_id="campaign_view",
                table_type="view",
            ),
        ]
    )
    await db.commit()
    return connection, resource


async def test_table_scope_routes_replace_list_tables_and_audit_without_values(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    connection, resource = await _bigquery_connection(db_session, integration_identity)
    base = f"/api/v1/integrations/connections/{connection.id}"

    tables_response = await db_async_client.get(
        f"{base}/resources/{resource.id}/tables",
        headers=integration_identity["headers"],
    )
    assert tables_response.status_code == 200, tables_response.text
    assert tables_response.json()["next_cursor"] is None
    assert tables_response.json()["tables"] == [
        {
            "table_external_id": "campaign_daily",
            "description": "Daily campaign performance",
            "columns": [
                {
                    "name": "account_id",
                    "column_type": "string",
                    "description": "Client account",
                },
                {
                    "name": "legacy_id",
                    "column_type": "integer",
                    "description": None,
                },
            ],
        }
    ]

    update = await db_async_client.put(
        f"{base}/table-scopes",
        headers=integration_identity["headers"],
        json={
            "rules": [
                {
                    "resource_id": str(resource.id),
                    "table_external_id": "campaign_daily",
                    "column_name": "legacy_id",
                    "allowed_values": [
                        "0",
                        "-42",
                        "0",
                        "-9223372036854775808",
                        "9223372036854775807",
                    ],
                }
            ]
        },
    )
    assert update.status_code == 200, update.text
    assert update.json()["rules"][0]["allowed_values"] == [
        "0",
        "-42",
        "-9223372036854775808",
        "9223372036854775807",
    ]

    listed = await db_async_client.get(
        f"{base}/table-scopes",
        headers=integration_identity["headers"],
    )
    assert listed.status_code == 200, listed.text
    assert listed.json() == update.json()

    event = await db_session.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.resource_type == "integration_connection",
            AuditEvent.resource_id == str(connection.id),
        )
        .order_by(AuditEvent.occurred_at.desc())
    )
    assert event is not None
    assert event.details == {
        "connection": "Client warehouse",
        "row_filter_count": 1,
        "tables": [
            {
                "resource": "analytics.marketing",
                "table": "campaign_daily",
                "column": "legacy_id",
            }
        ],
    }
    assert "-42" not in str(event.details)

    cleared = await db_async_client.put(
        f"{base}/table-scopes",
        headers=integration_identity["headers"],
        json={"rules": []},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["rules"] == []


async def test_table_scope_table_picker_uses_stable_cursor_pagination(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    connection, resource = await _bigquery_connection(db_session, integration_identity)
    db_session.add_all(
        [
            build_integration_table_schema(
                resource=resource,
                table_external_id="account_daily",
                schema_fields=[{"name": "account_id", "type": "STRING"}],
            ),
            build_integration_table_schema(
                resource=resource,
                table_external_id="spend_daily",
                schema_fields=[{"name": "account_id", "type": "STRING"}],
            ),
        ]
    )
    await db_session.commit()
    path = f"/api/v1/integrations/connections/{connection.id}/resources/{resource.id}/tables"

    first = await db_async_client.get(
        path,
        params={"limit": 1},
        headers=integration_identity["headers"],
    )
    assert first.status_code == 200, first.text
    assert [table["table_external_id"] for table in first.json()["tables"]] == ["account_daily"]
    assert first.json()["next_cursor"] == "account_daily"

    second = await db_async_client.get(
        path,
        params={"limit": 1, "cursor": first.json()["next_cursor"]},
        headers=integration_identity["headers"],
    )
    assert second.status_code == 200, second.text
    assert [table["table_external_id"] for table in second.json()["tables"]] == ["campaign_daily"]
    assert second.json()["next_cursor"] == "campaign_daily"

    final = await db_async_client.get(
        path,
        params={"limit": 1, "cursor": second.json()["next_cursor"]},
        headers=integration_identity["headers"],
    )
    assert final.status_code == 200, final.text
    assert [table["table_external_id"] for table in final.json()["tables"]] == ["spend_daily"]
    assert final.json()["next_cursor"] is None


@pytest.mark.parametrize(
    ("table", "column", "values", "expected_status"),
    [
        ("campaign_view", "account_id", ["account-1"], 400),
        ("campaign_daily", "tags", ["client"], 400),
        ("campaign_daily", "report_date", ["2026-08-25"], 400),
        ("campaign_daily", "legacy_id", [], 422),
        ("campaign_daily", "account_id", ["x" * 257], 400),
        ("campaign_daily", "legacy_id", ["1.5"], 400),
        ("campaign_daily", "legacy_id", ["9223372036854775808"], 400),
        ("campaign_daily", "legacy_id", ["-9223372036854775809"], 400),
    ],
)
async def test_table_scope_replace_validation_matrix(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
    table: str,
    column: str,
    values: list[str],
    expected_status: int,
) -> None:
    connection, resource = await _bigquery_connection(db_session, integration_identity)

    response = await db_async_client.put(
        f"/api/v1/integrations/connections/{connection.id}/table-scopes",
        headers=integration_identity["headers"],
        json={
            "rules": [
                {
                    "resource_id": str(resource.id),
                    "table_external_id": table,
                    "column_name": column,
                    "allowed_values": values,
                }
            ]
        },
    )

    assert response.status_code == expected_status, response.text


async def test_table_scope_routes_reject_foreign_resource_unsupported_provider_and_reader(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    connection, _resource = await _bigquery_connection(db_session, integration_identity)
    unsupported_credential = build_external_credential(
        provider_key="gmail",
        owner_user_id=integration_identity["user"].id,
    )
    unsupported_connection = build_integration_connection(
        credential=unsupported_credential,
        user=integration_identity["user"],
        owner_user_id=integration_identity["user"].id,
        status="active",
    )
    db_session.add_all([unsupported_credential, unsupported_connection])
    await db_session.commit()
    foreign_user, foreign_workspace, _membership, _headers = await create_identity(
        db_session,
        role=WorkspaceRole.OWNER,
    )
    foreign_identity = {"user": foreign_user, "workspace": foreign_workspace}
    _foreign_connection, foreign_resource = await _bigquery_connection(db_session, foreign_identity)
    invalid = await db_async_client.put(
        f"/api/v1/integrations/connections/{connection.id}/table-scopes",
        headers=integration_identity["headers"],
        json={
            "rules": [
                {
                    "resource_id": str(foreign_resource.id),
                    "table_external_id": "campaign_daily",
                    "column_name": "account_id",
                    "allowed_values": ["account-1"],
                }
            ]
        },
    )
    assert invalid.status_code == 400, invalid.text

    unsupported = await db_async_client.get(
        f"/api/v1/integrations/connections/{unsupported_connection.id}/table-scopes",
        headers=integration_identity["headers"],
    )
    assert unsupported.status_code == 400, unsupported.text

    _reader, _workspace, _membership, reader_headers = await create_identity(
        db_session,
        role=WorkspaceRole.READ_ONLY,
        workspace=integration_identity["workspace"],
    )
    forbidden = await db_async_client.get(
        f"/api/v1/integrations/connections/{connection.id}/table-scopes",
        headers=reader_headers,
    )
    assert forbidden.status_code == 403, forbidden.text


async def test_provider_listing_discloses_table_scope_support(
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    response = await db_async_client.get(
        "/api/v1/integrations/providers",
        headers=integration_identity["headers"],
    )

    assert response.status_code == 200, response.text
    providers = {item["provider_key"]: item for item in response.json()}
    assert providers["bigquery"]["table_scopes_supported"] is True
    assert providers["gmail"]["table_scopes_supported"] is False
