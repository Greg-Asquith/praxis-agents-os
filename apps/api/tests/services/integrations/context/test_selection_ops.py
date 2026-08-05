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
    MAX_ACTIVE_CONTEXT_TARGETS,
    ActiveContextSelectionValue,
    ActiveContextTargets,
    ContextGroupCreateRequest,
    ContextGroupUpdateRequest,
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


def _targets(*targets: ActiveContextSelectionValue) -> ActiveContextTargets:
    return ActiveContextTargets(targets=list(targets))


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


def test_target_set_is_capped_and_rejects_duplicates() -> None:
    resource = ActiveContextSelectionValue.for_resource(uuid4())

    with pytest.raises(ValidationError):
        ActiveContextTargets.model_validate({})
    with pytest.raises(ValidationError, match="must not contain duplicates"):
        ActiveContextTargets(targets=[resource, resource])
    with pytest.raises(ValidationError):
        ActiveContextTargets(
            targets=[
                ActiveContextSelectionValue.for_resource(uuid4())
                for _ in range(MAX_ACTIVE_CONTEXT_TARGETS + 1)
            ]
        )


def test_context_group_resource_set_is_capped() -> None:
    resource_ids = [uuid4() for _ in range(MAX_ACTIVE_CONTEXT_TARGETS + 1)]

    with pytest.raises(ValidationError):
        ContextGroupCreateRequest(name="Oversized", resource_ids=resource_ids)
    with pytest.raises(ValidationError):
        ContextGroupUpdateRequest(resource_ids=resource_ids)


async def test_selection_replace_set_and_clear_audit_once_per_operation(
    db_session: AsyncSession,
    context_data: dict[str, object],
) -> None:
    first = await set_active_context_selection(
        db_session,
        request=None,
        actor=context_data["user"],
        workspace=context_data["workspace"],
        conversation_id=context_data["conversation"].id,
        targets=_targets(
            ActiveContextSelectionValue.for_resource(context_data["first"].id),
            ActiveContextSelectionValue.for_resource(context_data["second"].id),
        ),
    )
    second = await set_active_context_selection(
        db_session,
        request=None,
        actor=context_data["user"],
        workspace=context_data["workspace"],
        conversation_id=context_data["conversation"].id,
        targets=_targets(ActiveContextSelectionValue.for_resource(context_data["second"].id)),
    )
    assert {selection.integration_resource_id for selection in first} == {
        context_data["first"].id,
        context_data["second"].id,
    }
    assert [selection.integration_resource_id for selection in second] == [
        context_data["second"].id
    ]
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
        == []
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
    replace_events = (
        await db_session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.resource_type == "active_context_selection",
                AuditEvent.action == "update",
                AuditEvent.workspace_id == context_data["workspace"].id,
            )
            .order_by(AuditEvent.occurred_at)
        )
    ).all()
    assert replace_events[0].resource_id == str(context_data["conversation"].id)
    assert {
        target["integration_resource_id"] for target in replace_events[0].details["targets"]
    } == {str(context_data["first"].id), str(context_data["second"].id)}


async def test_empty_target_set_clears_with_one_replace_audit(
    db_session: AsyncSession,
    context_data: dict[str, object],
) -> None:
    await set_active_context_selection(
        db_session,
        request=None,
        actor=context_data["user"],
        workspace=context_data["workspace"],
        conversation_id=context_data["conversation"].id,
        targets=_targets(ActiveContextSelectionValue.for_resource(context_data["first"].id)),
    )
    await set_active_context_selection(
        db_session,
        request=None,
        actor=context_data["user"],
        workspace=context_data["workspace"],
        conversation_id=context_data["conversation"].id,
        targets=ActiveContextTargets(targets=[]),
    )

    assert (
        await get_active_context_selection(
            db_session,
            actor=context_data["user"],
            workspace=context_data["workspace"],
            conversation_id=context_data["conversation"].id,
        )
        == []
    )
    latest = await db_session.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.resource_type == "active_context_selection",
            AuditEvent.action == "update",
        )
        .order_by(AuditEvent.occurred_at.desc())
    )
    assert latest is not None
    assert latest.details["targets"] == []


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
    selections = await set_active_context_selection(
        db_session,
        request=None,
        actor=context_data["user"],
        workspace=context_data["workspace"],
        conversation_id=context_data["conversation"].id,
        targets=_targets(ActiveContextSelectionValue.for_context_group(group.id)),
    )
    selection = selections[0]
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
        targets=_targets(ActiveContextSelectionValue.for_resource(context_data["first"].id)),
    )
    await set_active_context_selection(
        db_session,
        request=None,
        actor=context_data["user"],
        workspace=context_data["workspace"],
        conversation_id=other_conversation.id,
        targets=_targets(ActiveContextSelectionValue.for_resource(context_data["second"].id)),
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
    assert [selection.integration_resource_id for selection in first_selection] == [
        context_data["first"].id
    ]
    assert [selection.integration_resource_id for selection in second_selection] == [
        context_data["second"].id
    ]


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
                targets=_targets(ActiveContextSelectionValue.for_resource(resource_id)),
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
    await set_active_context_selection(
        db_session,
        request=None,
        actor=context_data["user"],
        workspace=context_data["workspace"],
        conversation_id=context_data["conversation"].id,
        targets=_targets(ActiveContextSelectionValue.for_resource(context_data["second"].id)),
    )
    with pytest.raises(NotFoundError):
        await set_active_context_selection(
            db_session,
            request=None,
            actor=context_data["user"],
            workspace=context_data["workspace"],
            conversation_id=context_data["conversation"].id,
            targets=_targets(
                ActiveContextSelectionValue.for_resource(context_data["first"].id),
                ActiveContextSelectionValue.for_resource(uuid4()),
            ),
        )

    assert [
        selection.integration_resource_id
        for selection in await get_active_context_selection(
            db_session,
            actor=context_data["user"],
            workspace=context_data["workspace"],
            conversation_id=context_data["conversation"].id,
        )
    ] == [context_data["second"].id]


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
            targets=_targets(ActiveContextSelectionValue.for_resource(resource.id)),
        )


async def test_selection_hides_another_users_personal_resource(
    db_session: AsyncSession,
    context_data: dict[str, object],
) -> None:
    other_user = build_user(email=f"personal-context-{uuid4().hex}@example.com")
    db_session.add(other_user)
    await db_session.flush()
    await set_session_tenant_context(
        db_session,
        workspace_id=context_data["workspace"].id,
        user_id=other_user.id,
    )
    credential = build_external_credential(principal_fingerprint="c" * 64)
    connection = build_integration_connection(
        credential=credential,
        user=other_user,
        owner_user_id=other_user.id,
    )
    resource = build_integration_resource(connection=connection)
    db_session.add_all([credential, connection, resource])
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
            targets=_targets(ActiveContextSelectionValue.for_resource(resource.id)),
        )
