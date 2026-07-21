# apps/api/tests/services/integrations/context/test_context_groups.py

"""Context-group service behavior."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from models.audit_event import AuditEvent
from models.integration_context import IntegrationContextGroup
from services.integrations.context import (
    create_context_group,
    delete_context_group,
    list_context_groups,
    update_context_group,
)
from services.integrations.context.schemas import (
    ContextGroupCreateRequest,
    ContextGroupUpdateRequest,
)
from tests.factories import (
    build_external_credential,
    build_integration_connection,
    build_integration_resource,
    build_user,
    build_workspace,
)


async def test_context_group_crud_replaces_members_and_audits(
    db_session: AsyncSession,
    context_data: dict[str, object],
) -> None:
    group = await create_context_group(
        db_session,
        request=None,
        actor=context_data["user"],
        workspace=context_data["workspace"],
        payload=ContextGroupCreateRequest(
            name="  Client accounts  ",
            resource_ids=[context_data["first"].id],
        ),
    )
    assert group.name == "Client accounts"
    assert [member.id for member in group.members] == [context_data["first"].id]

    updated = await update_context_group(
        db_session,
        request=None,
        actor=context_data["user"],
        workspace=context_data["workspace"],
        group_id=group.id,
        payload=ContextGroupUpdateRequest(
            name="Priority accounts",
            resource_ids=[context_data["second"].id],
        ),
    )
    assert updated.name == "Priority accounts"
    assert [member.id for member in updated.members] == [context_data["second"].id]
    listed = await list_context_groups(db_session, workspace=context_data["workspace"])
    assert [item.id for item in listed.items] == [group.id]

    await delete_context_group(
        db_session,
        request=None,
        actor=context_data["user"],
        workspace=context_data["workspace"],
        group_id=group.id,
    )
    assert (await list_context_groups(db_session, workspace=context_data["workspace"])).items == []
    persisted = await db_session.get(IntegrationContextGroup, group.id)
    assert persisted is not None and persisted.deleted is True
    events = (
        await db_session.scalars(
            select(AuditEvent).where(
                AuditEvent.resource_type == "integration_context_group",
                AuditEvent.resource_id == str(group.id),
            )
        )
    ).all()
    assert [event.action for event in events] == ["create", "update", "delete"]


async def test_context_group_name_is_unique_case_insensitively_per_workspace(
    db_session: AsyncSession,
    context_data: dict[str, object],
) -> None:
    await create_context_group(
        db_session,
        request=None,
        actor=context_data["user"],
        workspace=context_data["workspace"],
        payload=ContextGroupCreateRequest(name="Accounts", resource_ids=[]),
    )
    with pytest.raises(ConflictError):
        await create_context_group(
            db_session,
            request=None,
            actor=context_data["user"],
            workspace=context_data["workspace"],
            payload=ContextGroupCreateRequest(name="accounts", resource_ids=[]),
        )


async def test_context_group_rejects_foreign_workspace_resource(
    db_session: AsyncSession,
    context_data: dict[str, object],
) -> None:
    other_user = build_user(email=f"foreign-{uuid4().hex}@example.com")
    other_workspace = build_workspace(slug=f"foreign-{uuid4().hex[:8]}")
    credential = build_external_credential(principal_fingerprint="a" * 64)
    db_session.add_all([other_user, other_workspace, credential])
    await db_session.flush()
    connection = build_integration_connection(
        credential=credential,
        user=other_user,
        workspace=other_workspace,
    )
    db_session.add(connection)
    await db_session.flush()
    foreign_resource = build_integration_resource(connection=connection)
    db_session.add(foreign_resource)
    await db_session.flush()

    with pytest.raises(AppValidationError):
        await create_context_group(
            db_session,
            request=None,
            actor=context_data["user"],
            workspace=context_data["workspace"],
            payload=ContextGroupCreateRequest(
                name="Foreign",
                resource_ids=[foreign_resource.id],
            ),
        )


async def test_context_group_cross_workspace_id_is_hidden(
    db_session: AsyncSession,
    context_data: dict[str, object],
) -> None:
    with pytest.raises(NotFoundError):
        await update_context_group(
            db_session,
            request=None,
            actor=context_data["user"],
            workspace=context_data["workspace"],
            group_id=uuid4(),
            payload=ContextGroupUpdateRequest(name="Missing"),
        )
