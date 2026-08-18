# apps/api/tests/services/integrations/context/test_context_groups.py

"""Context-group service behavior."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import set_session_tenant_context
from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from models.audit_event import AuditEvent
from models.integration_context import IntegrationContextGroup
from models.integrations import IntegrationResource
from models.user import User
from models.workspace import Workspace, WorkspaceRole
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
    build_workspace_membership,
)


async def _add_resource(
    db_session: AsyncSession,
    *,
    user: User,
    workspace: Workspace | None,
    provider_key: str,
    resource_type: str,
) -> IntegrationResource:
    credential = build_external_credential(
        provider_key=provider_key,
        principal_fingerprint=uuid4().hex.ljust(64, "0"),
    )
    db_session.add(credential)
    await db_session.flush()
    connection = build_integration_connection(
        credential=credential,
        user=user,
        workspace=workspace,
        owner_user_id=user.id if workspace is None else None,
        status="active",
    )
    db_session.add(connection)
    await db_session.flush()
    resource = build_integration_resource(
        connection=connection,
        resource_type=resource_type,
        external_id=f"{provider_key}-{uuid4().hex}",
        enabled=True,
    )
    db_session.add(resource)
    await db_session.flush()
    return resource


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
            select(AuditEvent)
            .where(
                AuditEvent.resource_type == "integration_context_group",
                AuditEvent.resource_id == str(group.id),
            )
            .order_by(AuditEvent.occurred_at, AuditEvent.id)
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
    db_session.add_all([other_user, other_workspace])
    await db_session.flush()
    await set_session_tenant_context(
        db_session,
        workspace_id=other_workspace.id,
        user_id=other_user.id,
    )
    credential = build_external_credential(principal_fingerprint="a" * 64)
    db_session.add(credential)
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
    await set_session_tenant_context(
        db_session,
        workspace_id=context_data["workspace"].id,
        user_id=context_data["user"].id,
    )

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


async def test_shared_context_group_rejects_actor_owned_resource(
    db_session: AsyncSession,
    context_data: dict[str, object],
) -> None:
    resource = await _add_resource(
        db_session,
        user=context_data["user"],
        workspace=None,
        provider_key="gmail",
        resource_type="gmail_mailbox",
    )

    with pytest.raises(AppValidationError, match="available to Context Groups") as exc_info:
        await create_context_group(
            db_session,
            request=None,
            actor=context_data["user"],
            workspace=context_data["workspace"],
            payload=ContextGroupCreateRequest(name="Personal inbox", resource_ids=[resource.id]),
        )

    assert exc_info.value.field == "resource_ids"


async def test_shared_context_group_accepts_mixed_workspace_owned_providers(
    db_session: AsyncSession,
    context_data: dict[str, object],
) -> None:
    google_analytics = await _add_resource(
        db_session,
        user=context_data["user"],
        workspace=context_data["workspace"],
        provider_key="google_analytics",
        resource_type="google_analytics_property",
    )
    google_ads = await _add_resource(
        db_session,
        user=context_data["user"],
        workspace=context_data["workspace"],
        provider_key="google_ads",
        resource_type="google_ads_account",
    )

    group = await create_context_group(
        db_session,
        request=None,
        actor=context_data["user"],
        workspace=context_data["workspace"],
        payload=ContextGroupCreateRequest(
            name="Mixed providers",
            resource_ids=[google_ads.id, google_analytics.id],
        ),
    )

    assert {member.id for member in group.members} == {google_ads.id, google_analytics.id}


async def test_personal_context_group_accepts_actor_and_workspace_owned_resources(
    db_session: AsyncSession,
    context_data: dict[str, object],
) -> None:
    workspace = context_data["workspace"]
    workspace.is_personal = True
    gmail = await _add_resource(
        db_session,
        user=context_data["user"],
        workspace=None,
        provider_key="gmail",
        resource_type="gmail_mailbox",
    )
    google_ads = await _add_resource(
        db_session,
        user=context_data["user"],
        workspace=workspace,
        provider_key="google_ads",
        resource_type="google_ads_account",
    )

    group = await create_context_group(
        db_session,
        request=None,
        actor=context_data["user"],
        workspace=workspace,
        payload=ContextGroupCreateRequest(
            name="My accounts",
            resource_ids=[gmail.id, google_ads.id],
        ),
    )

    assert {member.id for member in group.members} == {gmail.id, google_ads.id}


async def test_personal_context_group_rejects_another_workspace_resource(
    db_session: AsyncSession,
    context_data: dict[str, object],
) -> None:
    workspace = context_data["workspace"]
    workspace.is_personal = True
    other_workspace = build_workspace(slug=f"other-{uuid4().hex[:8]}")
    membership = build_workspace_membership(
        workspace_id=other_workspace.id,
        user_id=context_data["user"].id,
        role=WorkspaceRole.OWNER,
    )
    db_session.add_all([other_workspace, membership])
    await db_session.flush()
    await set_session_tenant_context(
        db_session,
        workspace_id=other_workspace.id,
        user_id=context_data["user"].id,
    )
    foreign_resource = await _add_resource(
        db_session,
        user=context_data["user"],
        workspace=other_workspace,
        provider_key="google_ads",
        resource_type="google_ads_account",
    )
    await set_session_tenant_context(
        db_session,
        workspace_id=workspace.id,
        user_id=context_data["user"].id,
    )

    with pytest.raises(AppValidationError):
        await create_context_group(
            db_session,
            request=None,
            actor=context_data["user"],
            workspace=workspace,
            payload=ContextGroupCreateRequest(
                name="Other workspace",
                resource_ids=[foreign_resource.id],
            ),
        )


async def test_shared_context_group_rejects_ineligible_update_atomically(
    db_session: AsyncSession,
    context_data: dict[str, object],
) -> None:
    group = await create_context_group(
        db_session,
        request=None,
        actor=context_data["user"],
        workspace=context_data["workspace"],
        payload=ContextGroupCreateRequest(
            name="Shared accounts",
            resource_ids=[context_data["first"].id],
        ),
    )
    personal_resource = await _add_resource(
        db_session,
        user=context_data["user"],
        workspace=None,
        provider_key="gmail",
        resource_type="gmail_mailbox",
    )

    with pytest.raises(AppValidationError):
        await update_context_group(
            db_session,
            request=None,
            actor=context_data["user"],
            workspace=context_data["workspace"],
            group_id=group.id,
            payload=ContextGroupUpdateRequest(
                resource_ids=[context_data["second"].id, personal_resource.id]
            ),
        )

    persisted = await list_context_groups(db_session, workspace=context_data["workspace"])
    assert [member.id for member in persisted.items[0].members] == [context_data["first"].id]


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
