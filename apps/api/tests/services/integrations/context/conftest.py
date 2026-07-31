# apps/api/tests/services/integrations/context/conftest.py

"""Shared persisted objects for integration-context service tests."""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import (
    build_conversation,
    build_external_credential,
    build_integration_connection,
    build_integration_resource,
    build_user,
    build_workspace,
    build_workspace_membership,
)


@pytest_asyncio.fixture
async def context_data(db_session: AsyncSession) -> AsyncIterator[dict[str, object]]:
    suffix = uuid4().hex
    user = build_user(email=f"context-{suffix}@example.com")
    workspace = build_workspace(slug=f"context-{suffix[:8]}")
    credential = build_external_credential(principal_fingerprint=suffix.ljust(64, "0"))
    db_session.add_all([user, workspace, credential])
    await db_session.flush()
    db_session.add(build_workspace_membership(workspace_id=workspace.id, user_id=user.id))
    await db_session.flush()
    conversation = build_conversation(user=user, workspace=workspace)
    db_session.add(conversation)
    await db_session.flush()
    connection = build_integration_connection(
        credential=credential,
        user=user,
        workspace=workspace,
        status="active",
    )
    db_session.add(connection)
    await db_session.flush()
    first = build_integration_resource(
        connection=connection,
        external_id="first",
        display_name="First resource",
        enabled=True,
    )
    second = build_integration_resource(
        connection=connection,
        external_id="second",
        display_name="Second resource",
        enabled=True,
    )
    db_session.add_all([first, second])
    await db_session.flush()
    yield {
        "user": user,
        "workspace": workspace,
        "credential": credential,
        "conversation": conversation,
        "connection": connection,
        "first": first,
        "second": second,
    }
