# apps/api/tests/services/workspaces/test_custom_hooks.py

"""Deployment hooks run at the right point in core sign-in and workspace operations."""

import importlib
from unittest.mock import AsyncMock

import pytest
from fastapi import Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import SESSION_WORKSPACE_ID_KEY
from core.exceptions.auth import AuthorizationError
from models.workspace import WorkspaceRole
from services.auth.utils import issue_auth_response
from services.security import SecurityEventType
from services.workspaces import create_workspace
from services.workspaces.memberships import delete_membership
from services.workspaces.schemas import WorkspaceCreateRequest
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.requests import build_test_request

pytestmark = pytest.mark.asyncio


async def test_sign_in_hook_waits_for_the_two_factor_step(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = build_user(email="member@example.com")
    db_session.add(user)
    await db_session.flush()
    hook = AsyncMock()
    monkeypatch.setattr("services.auth.utils.after_sign_in", hook)

    for require_twofa in (True, False):
        await issue_auth_response(
            db_session,
            request=build_test_request(path="/api/v1/auth/login", method="POST"),
            response=Response(),
            user=user,
            event_type=SecurityEventType.AUTH_LOGIN_SUCCEEDED,
            details={},
            require_twofa=require_twofa,
        )
        assert hook.await_count == (0 if require_twofa else 1)


async def test_workspace_hook_runs_inside_the_new_workspace_context(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor = build_user(email="owner@example.com")
    db_session.add(actor)
    await db_session.flush()
    seen = []

    async def hook(db: AsyncSession, *, workspace, actor, request) -> None:
        seen.append((workspace.id, db.info.get(SESSION_WORKSPACE_ID_KEY)))

    module = importlib.import_module("services.workspaces.create_workspace")
    monkeypatch.setattr(module, "after_workspace_created", hook)

    result = await create_workspace(
        db_session,
        request=build_test_request(path="/api/v1/workspaces/"),
        actor=actor,
        payload=WorkspaceCreateRequest(name="Agent Team"),
    )

    assert [(workspace_id, str(context)) for workspace_id, context in seen] == [
        (result.id, str(result.id))
    ]


async def test_membership_hook_can_reject_a_removal(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = build_user(email="owner@example.com")
    target = build_user(email="protected@example.com")
    workspace = build_workspace(slug="team-workspace", is_personal=False)
    owner_membership = build_workspace_membership(
        workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.OWNER
    )
    target_membership = build_workspace_membership(
        workspace_id=workspace.id, user_id=target.id, role=WorkspaceRole.ADMIN
    )
    db_session.add_all([owner, target, workspace, owner_membership, target_membership])
    await db_session.flush()
    monkeypatch.setattr(
        importlib.import_module("services.workspaces.memberships.delete_membership"),
        "before_membership_change",
        AsyncMock(side_effect=AuthorizationError("This member can't be removed")),
    )

    with pytest.raises(AuthorizationError, match="can't be removed"):
        await delete_membership(
            db_session,
            request=build_test_request(
                path=f"/api/v1/workspaces/{workspace.id}/memberships/{target_membership.id}",
                method="DELETE",
            ),
            actor=owner,
            workspace_id=workspace.id,
            membership_id=target_membership.id,
        )

    assert target_membership.deleted is False
