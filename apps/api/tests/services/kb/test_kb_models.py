"""Database-enforced Knowledge Base model invariants."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from services.kb.domain import (
    KB_SOURCE_INTEGRATION,
    KB_SOURCE_MANUAL,
    KB_SOURCE_URL,
    KB_SYNC_DISCONNECTED,
    KB_SYNC_ERROR,
    KB_SYNC_PENDING,
    KB_SYNC_READY,
    KB_SYNC_UNAVAILABLE,
)
from tests.factories import (
    build_external_credential,
    build_integration_connection,
    build_integration_resource,
    build_kb_document,
)

pytestmark = pytest.mark.asyncio


async def test_refreshable_source_binding_checks(db_session, kb_actors) -> None:
    credential = build_external_credential()
    connection = build_integration_connection(
        credential=credential,
        user=kb_actors.user,
        workspace=kb_actors.workspace,
    )
    resource = build_integration_resource(connection=connection)
    db_session.add_all([credential, connection, resource])
    await db_session.flush()

    invalid_bindings = (
        {
            "source_type": KB_SOURCE_INTEGRATION,
            "external_id": None,
            "source_sync_status": KB_SYNC_PENDING,
        },
        {
            "source_type": KB_SOURCE_INTEGRATION,
            "external_id": "page-id",
            "source_sync_status": None,
        },
        {
            "source_type": KB_SOURCE_URL,
            "source_sync_status": None,
        },
        {
            "source_type": KB_SOURCE_URL,
            "source_sync_status": KB_SYNC_PENDING,
            "integration_resource_id": resource.id,
        },
        {
            "source_type": KB_SOURCE_MANUAL,
            "source_sync_status": KB_SYNC_PENDING,
        },
        {"source_synced_at": datetime.now(UTC)},
    )

    for invalid_binding in invalid_bindings:
        async with db_session.begin_nested():
            with pytest.raises(IntegrityError):
                db_session.add(
                    build_kb_document(
                        workspace=kb_actors.workspace,
                        **invalid_binding,
                    )
                )
                await db_session.flush()


async def test_integration_source_sync_status_check(db_session, kb_actors) -> None:
    for source_sync_status in (
        KB_SYNC_PENDING,
        KB_SYNC_READY,
        KB_SYNC_UNAVAILABLE,
        KB_SYNC_DISCONNECTED,
        KB_SYNC_ERROR,
    ):
        db_session.add(
            build_kb_document(
                workspace=kb_actors.workspace,
                source_type=KB_SOURCE_INTEGRATION,
                external_id=f"page-{source_sync_status}",
                source_sync_status=source_sync_status,
            )
        )
    await db_session.flush()

    async with db_session.begin_nested():
        with pytest.raises(IntegrityError):
            db_session.add(
                build_kb_document(
                    workspace=kb_actors.workspace,
                    source_type=KB_SOURCE_INTEGRATION,
                    external_id="page-invalid",
                    source_sync_status="invalid",
                )
            )
            await db_session.flush()
