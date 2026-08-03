# apps/api/tests/services/integrations/context/test_selection_ops.py

"""Active-context selection service behavior."""

import asyncio
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import set_session_tenant_context
from core.exceptions.general import NotFoundError
from models.audit_event import AuditEvent
from models.conversation import Conversation
from models.integration_context import ActiveContextSelection
from models.integrations import ExternalCredential, IntegrationConnection
from services.integrations.context import (
    clear_active_context_selection,
    create_context_group,
    get_active_context_selection,
    set_active_context_selection,
)
from services.integrations.context.schemas import (
    ActiveContextSelectionValue,
    ContextGroupCreateRequest,
)
from tests.factories import (
    build_conversation,
    build_external_credential,
    build_integration_connection,
    build_integration_resource,
    build_user,
    build_workspace,
    build_workspace_membership,
)


def test_selection_value_is_a_strict_discriminated_shape() -> None:
    resource_id = uuid4()
    selection = ActiveContextSelectionValue.model_validate(
        {"type": "resource", "integration_resource_id": resource_id}
    )

    assert selection.model_dump() == {
        "type": "resource",
        "integration_resource_id": resource_id,
    }
    with pytest.raises(ValidationError):
        ActiveContextSelectionValue.model_validate(
            {
                "type": "resource",
                "integration_resource_id": resource_id,
                "context_group_id": uuid4(),
            }
        )
    with pytest.raises(ValidationError):
        ActiveContextSelectionValue.model_validate(
            {
                "type": "context_group",
                "context_group_id": uuid4(),
                "unexpected": True,
            }
        )


async def test_selection_upsert_keeps_one_row_and_clear_audits(
    db_session: AsyncSession,
    context_data: dict[str, object],
) -> None:
    first = await set_active_context_selection(
        db_session,
        request=None,
        actor=context_data["user"],
        workspace=context_data["workspace"],
        conversation_id=context_data["conversation"].id,
        selection=ActiveContextSelectionValue.for_resource(context_data["first"].id),
    )
    second = await set_active_context_selection(
        db_session,
        request=None,
        actor=context_data["user"],
        workspace=context_data["workspace"],
        conversation_id=context_data["conversation"].id,
        selection=ActiveContextSelectionValue.for_resource(context_data["second"].id),
    )
    assert second.id == first.id
    assert second.integration_resource_id == context_data["second"].id
    count = await db_session.scalar(
        select(func.count())
        .select_from(ActiveContextSelection)
        .where(ActiveContextSelection.conversation_id == context_data["conversation"].id)
    )
    assert count == 1

    await clear_active_context_selection(
        db_session,
        request=None,
        actor=context_data["user"],
        workspace=context_data["workspace"],
        conversation_id=context_data["conversation"].id,
    )
    assert (
        await get_active_context_selection(
            db_session,
            actor=context_data["user"],
            workspace=context_data["workspace"],
            conversation_id=context_data["conversation"].id,
        )
        is None
    )
    actions = (
        await db_session.scalars(
            select(AuditEvent.action)
            .where(
                AuditEvent.resource_type == "active_context_selection",
                AuditEvent.workspace_id == context_data["workspace"].id,
            )
            .order_by(AuditEvent.occurred_at)
        )
    ).all()
    assert actions == ["update", "update", "delete"]


async def test_selection_accepts_a_workspace_group(
    db_session: AsyncSession,
    context_data: dict[str, object],
) -> None:
    group = await create_context_group(
        db_session,
        request=None,
        actor=context_data["user"],
        workspace=context_data["workspace"],
        payload=ContextGroupCreateRequest(
            name="Group",
            resource_ids=[context_data["first"].id],
        ),
    )
    selection = await set_active_context_selection(
        db_session,
        request=None,
        actor=context_data["user"],
        workspace=context_data["workspace"],
        conversation_id=context_data["conversation"].id,
        selection=ActiveContextSelectionValue.for_context_group(group.id),
    )
    assert selection.context_group_id == group.id
    assert selection.integration_resource_id is None


async def test_each_conversation_restores_its_own_active_context(
    db_session: AsyncSession,
    context_data: dict[str, object],
) -> None:
    other_conversation = build_conversation(
        user=context_data["user"],
        workspace=context_data["workspace"],
        title="Second conversation",
    )
    db_session.add(other_conversation)
    await db_session.flush()

    await set_active_context_selection(
        db_session,
        request=None,
        actor=context_data["user"],
        workspace=context_data["workspace"],
        conversation_id=context_data["conversation"].id,
        selection=ActiveContextSelectionValue.for_resource(context_data["first"].id),
    )
    await set_active_context_selection(
        db_session,
        request=None,
        actor=context_data["user"],
        workspace=context_data["workspace"],
        conversation_id=other_conversation.id,
        selection=ActiveContextSelectionValue.for_resource(context_data["second"].id),
    )

    first_selection = await get_active_context_selection(
        db_session,
        actor=context_data["user"],
        workspace=context_data["workspace"],
        conversation_id=context_data["conversation"].id,
    )
    second_selection = await get_active_context_selection(
        db_session,
        actor=context_data["user"],
        workspace=context_data["workspace"],
        conversation_id=other_conversation.id,
    )
    assert first_selection is not None
    assert second_selection is not None
    assert first_selection.integration_resource_id == context_data["first"].id
    assert second_selection.integration_resource_id == context_data["second"].id


async def test_concurrent_selection_upserts_never_create_duplicate_rows(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    suffix = uuid4().hex
    user = build_user(email=f"concurrent-context-{suffix}@example.com")
    workspace = build_workspace(slug=f"concurrent-context-{suffix[:8]}")
    credential = build_external_credential(
        auth_mode="api_key",
        access_token_encrypted=None,
        secret_provider="local_env",  # noqa: S106 - inert test reference metadata
        secret_name=f"concurrent-context-{suffix}",
        secret_version="latest",  # noqa: S106 - inert test metadata
        principal_fingerprint=suffix.ljust(64, "0"),
    )
    async with committed_db_session_factory() as setup_db:
        setup_db.add_all([user, workspace, credential])
        await setup_db.flush()
        setup_db.add(build_workspace_membership(workspace_id=workspace.id, user_id=user.id))
        await setup_db.flush()
        conversation = build_conversation(user=user, workspace=workspace)
        setup_db.add(conversation)
        await setup_db.flush()
        connection = build_integration_connection(
            credential=credential,
            user=user,
            workspace=workspace,
        )
        setup_db.add(connection)
        await setup_db.flush()
        resources = [
            build_integration_resource(
                connection=connection,
                external_id=f"concurrent-{index}",
            )
            for index in range(2)
        ]
        setup_db.add_all(resources)
        await setup_db.commit()

    async def select_resource(resource_id: UUID) -> None:
        async with committed_db_session_factory() as db:
            await set_active_context_selection(
                db,
                request=None,
                actor=user,
                workspace=workspace,
                conversation_id=conversation.id,
                selection=ActiveContextSelectionValue.for_resource(resource_id),
            )
            await db.commit()

    try:
        await asyncio.gather(*(select_resource(resource.id) for resource in resources))

        async with committed_db_session_factory() as verify_db:
            count = await verify_db.scalar(
                select(func.count())
                .select_from(ActiveContextSelection)
                .where(
                    ActiveContextSelection.conversation_id == conversation.id,
                    ActiveContextSelection.workspace_id == workspace.id,
                )
            )
        assert count == 1
    finally:
        async with committed_db_session_factory() as cleanup_db:
            await cleanup_db.execute(delete(Conversation).where(Conversation.id == conversation.id))
            await cleanup_db.execute(
                delete(IntegrationConnection).where(IntegrationConnection.id == connection.id)
            )
            await cleanup_db.execute(
                delete(ExternalCredential).where(ExternalCredential.id == credential.id)
            )
            await cleanup_db.commit()


async def test_selection_rejects_dangling_target(
    db_session: AsyncSession,
    context_data: dict[str, object],
) -> None:
    with pytest.raises(NotFoundError):
        await set_active_context_selection(
            db_session,
            request=None,
            actor=context_data["user"],
            workspace=context_data["workspace"],
            conversation_id=context_data["conversation"].id,
            selection=ActiveContextSelectionValue.for_resource(uuid4()),
        )


async def test_selection_hides_cross_workspace_resource(
    db_session: AsyncSession,
    context_data: dict[str, object],
) -> None:
    other_user = build_user(email=f"foreign-selection-{uuid4().hex}@example.com")
    other_workspace = build_workspace(slug=f"foreign-selection-{uuid4().hex[:8]}")
    db_session.add_all([other_user, other_workspace])
    await db_session.flush()
    await set_session_tenant_context(
        db_session,
        workspace_id=other_workspace.id,
        user_id=other_user.id,
    )
    credential = build_external_credential(principal_fingerprint="b" * 64)
    db_session.add(credential)
    await db_session.flush()
    connection = build_integration_connection(
        credential=credential,
        user=other_user,
        workspace=other_workspace,
    )
    db_session.add(connection)
    await db_session.flush()
    resource = build_integration_resource(connection=connection)
    db_session.add(resource)
    await db_session.flush()
    await set_session_tenant_context(
        db_session,
        workspace_id=context_data["workspace"].id,
        user_id=context_data["user"].id,
    )

    with pytest.raises(NotFoundError):
        await set_active_context_selection(
            db_session,
            request=None,
            actor=context_data["user"],
            workspace=context_data["workspace"],
            conversation_id=context_data["conversation"].id,
            selection=ActiveContextSelectionValue.for_resource(resource.id),
        )
