# apps/api/tests/services/workspaces/test_invitation_audit_context.py

"""Tests invitation audit writes without fixture tenant inference."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import (
    SESSION_USER_ID_KEY,
    SESSION_WORKSPACE_ID_KEY,
    get_maintenance_async_db_session_factory,
    set_session_tenant_context,
    tenant_context,
)
from models.audit_event import AuditEvent
from models.user import UserAuth
from models.workspace import WorkspaceInvitation, WorkspaceMembership, WorkspaceRole
from services.audit_events import AuditAction, AuditActorType, AuditResourceType
from services.audit_events.operations import record_operation_audit_event
from services.workspaces.invitations import (
    accept_invitation_by_token,
    accept_pending_invitations_for_user,
)
from tests.factories import build_user, build_workspace, build_workspace_membership


@pytest_asyncio.fixture
async def invitation_context(db_session_factory):
    owner = build_user(email="alex@example.com")
    invited = build_user(email="dana@example.com")
    personal = build_workspace(slug="personal", is_personal=True)
    teams = [build_workspace(slug="team-one"), build_workspace(slug="team-two")]
    created_at = datetime.now(UTC)
    invitations = [
        WorkspaceInvitation(
            workspace_id=workspace.id,
            email=invited.email,
            role=WorkspaceRole.ADMIN.value,
            invited_by=owner.id,
            token_hash=WorkspaceInvitation.hash_raw_token(workspace.slug),
            expires_at=datetime.now(UTC) + timedelta(days=1),
            created_at=created_at + timedelta(microseconds=index),
        )
        for index, workspace in enumerate(teams)
    ]
    async with get_maintenance_async_db_session_factory()() as setup:
        setup.add_all(
            [
                owner,
                invited,
                personal,
                *teams,
                UserAuth(
                    user_id=invited.id,
                    provider="google",
                    provider_user_id="verified-dana",
                    email=invited.email,
                    email_verified=True,
                ),
                build_workspace_membership(
                    workspace_id=personal.id, user_id=invited.id, role=WorkspaceRole.OWNER
                ),
                *[
                    build_workspace_membership(
                        workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.OWNER
                    )
                    for workspace in teams
                ],
                *invitations,
            ]
        )
        await setup.flush()
        await record_operation_audit_event(
            setup,
            workspace_id=personal.id,
            action=AuditAction.CREATE,
            resource_type=AuditResourceType.WORKSPACE,
            resource_id=personal.id,
            actor_type=AuditActorType.USER,
            actor_id=invited.id,
        )
        await setup.commit()

    # Plain sessions exercise the production role and context hooks only.
    async with AsyncSession(
        bind=db_session_factory.kw["bind"],
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    ) as runtime:
        yield runtime, owner, invited, personal, invitations


async def test_pending_invitation_audits_restore_the_callers_context(invitation_context):
    db, owner, invited, personal, invitations = invitation_context
    await set_session_tenant_context(db, workspace_id=personal.id, user_id=owner.id)

    assert await accept_pending_invitations_for_user(db, user=invited) == 2
    assert db.info[SESSION_WORKSPACE_ID_KEY] == personal.id
    assert db.info[SESSION_USER_ID_KEY] == owner.id
    assert await db.scalar(text("SELECT current_setting('app.current_user_id')::uuid")) == owner.id
    assert [event.workspace_id for event in await db.scalars(select(AuditEvent))] == [personal.id]
    await db.commit()

    async with get_maintenance_async_db_session_factory()() as check:
        events = (
            await check.scalars(
                select(AuditEvent).where(
                    AuditEvent.resource_type == AuditResourceType.INVITATION.value,
                )
            )
        ).all()
        assert {event.resource_id for event in events} == {str(invite.id) for invite in invitations}
        for event in events:
            assert event.actor_user_id == invited.id
            assert event.details["role"] == WorkspaceRole.ADMIN.value
            membership = await check.get(WorkspaceMembership, event.details["membership_id"])
            assert membership is not None
            assert membership.workspace_id == event.workspace_id
            assert membership.user_id == invited.id


async def test_pending_invitation_audits_restore_missing_context_fail_closed(invitation_context):
    db, _owner, invited, _personal, invitations = invitation_context

    assert await db.scalar(select(AuditEvent.id)) is None
    assert await accept_pending_invitations_for_user(db, user=invited) == 2
    assert (await db.scalars(select(AuditEvent))).all() == []
    await db.commit()
    assert (await db.scalars(select(AuditEvent))).all() == []

    async with get_maintenance_async_db_session_factory()() as check:
        events = (
            await check.scalars(
                select(AuditEvent).where(
                    AuditEvent.resource_type == AuditResourceType.INVITATION.value,
                )
            )
        ).all()
        assert {event.resource_id for event in events} == {str(invite.id) for invite in invitations}


async def test_failed_invitation_audit_rolls_back_membership_and_restores_context(
    invitation_context, monkeypatch: pytest.MonkeyPatch
):
    import services.workspaces.invitations.accept_invitation_utils as acceptance

    db, owner, invited, personal, invitations = invitation_context
    failed_id = invitations[0].id
    await set_session_tenant_context(db, workspace_id=personal.id, user_id=owner.id)

    async def reject_one_audit(session, **kwargs):
        if kwargs["resource_id"] == failed_id:
            kwargs["workspace_id"] = uuid4()
        return await record_operation_audit_event(session, **kwargs)

    monkeypatch.setattr(acceptance, "record_operation_audit_event", reject_one_audit)

    assert await accept_pending_invitations_for_user(db, user=invited) == 1
    assert db.info[SESSION_WORKSPACE_ID_KEY] == personal.id
    assert db.info[SESSION_USER_ID_KEY] == owner.id
    assert [event.workspace_id for event in await db.scalars(select(AuditEvent))] == [personal.id]
    await db.commit()

    async with get_maintenance_async_db_session_factory()() as check:
        failed = await check.get(WorkspaceInvitation, failed_id)
        assert failed.accepted_at is None
        assert (
            await check.scalar(
                select(WorkspaceMembership.id).where(
                    WorkspaceMembership.workspace_id == failed.workspace_id,
                    WorkspaceMembership.user_id == invited.id,
                )
            )
            is None
        )
        events = (
            await check.scalars(
                select(AuditEvent).where(
                    AuditEvent.resource_type == AuditResourceType.INVITATION.value,
                )
            )
        ).all()
        assert [event.resource_id for event in events] == [str(invitations[1].id)]


async def test_failed_invitation_audits_without_context_leave_reads_fail_closed(
    invitation_context, monkeypatch: pytest.MonkeyPatch
):
    import services.workspaces.invitations.accept_invitation_utils as acceptance

    db, _owner, invited, _personal, _invitations = invitation_context

    async def reject_audit(session, **kwargs):
        kwargs["workspace_id"] = uuid4()
        return await record_operation_audit_event(session, **kwargs)

    monkeypatch.setattr(acceptance, "record_operation_audit_event", reject_audit)

    assert await accept_pending_invitations_for_user(db, user=invited) == 0
    assert (await db.scalars(select(AuditEvent))).all() == []
    await db.commit()
    assert (await db.scalars(select(AuditEvent))).all() == []


async def test_token_acceptance_audits_the_invited_workspace_and_restores_context(
    invitation_context,
):
    db, _owner, invited, personal, invitations = invitation_context
    await set_session_tenant_context(db, workspace_id=personal.id, user_id=invited.id)
    raw_token = "team-one"

    response = await accept_invitation_by_token(db, actor=invited, token=raw_token)

    assert response.status == "accepted"
    assert db.info[SESSION_WORKSPACE_ID_KEY] == personal.id
    assert [event.workspace_id for event in await db.scalars(select(AuditEvent))] == [personal.id]
    await db.commit()
    async with get_maintenance_async_db_session_factory()() as check:
        event = await check.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_id == str(invitations[0].id),
            )
        )
        assert event is not None
        assert event.workspace_id == invitations[0].workspace_id
        assert event.details["identity_proof"] == "invitation_token"


async def test_tenant_context_restores_ids_without_masking_a_query_failure(invitation_context):
    db, owner, invited, personal, invitations = invitation_context
    await set_session_tenant_context(db, workspace_id=personal.id, user_id=owner.id)

    with pytest.raises(DBAPIError, match="division by zero"):
        async with db.begin_nested():
            async with tenant_context(
                db, workspace_id=invitations[0].workspace_id, user_id=invited.id
            ):
                await db.execute(text("SELECT 1 / 0"))

    assert db.info[SESSION_WORKSPACE_ID_KEY] == personal.id
    assert db.info[SESSION_USER_ID_KEY] == owner.id
    assert [event.workspace_id for event in await db.scalars(select(AuditEvent))] == [personal.id]
