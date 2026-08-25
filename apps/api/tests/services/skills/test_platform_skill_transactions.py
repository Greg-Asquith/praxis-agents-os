"""Transaction-boundary tests for platform skill mutations."""

import importlib
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.skills import SkillScope
from services.skills.schemas import SkillCreateRequest, SkillUpdateRequest
from tests.factories import (
    build_skill,
    build_user,
    build_workspace,
    build_workspace_membership,
)

pytestmark = pytest.mark.asyncio


def _request() -> Request:
    return Request({"type": "http", "headers": []})


def _platform_context(monkeypatch: pytest.MonkeyPatch):
    admin_email = f"platform-skill-admin-{uuid4().hex}@example.com"
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", admin_email)
    actor = build_user(email=admin_email)
    workspace = build_workspace()
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=actor.id,
    )
    skill = build_skill(
        workspace=workspace,
        created_by=actor,
        scope=SkillScope.PLATFORM,
        workspace_id=None,
    )
    return actor, workspace, membership, skill


async def test_platform_create_stops_before_maintenance_write_when_request_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("services.skills.create_skill")
    actor, workspace, membership, _skill = _platform_context(monkeypatch)
    db = AsyncMock(spec=AsyncSession)
    db.commit.side_effect = RuntimeError("request commit failed")
    platform_write = AsyncMock()
    monkeypatch.setattr(module, "_create_platform_skill", platform_write)

    with pytest.raises(RuntimeError, match="request commit failed"):
        await module.create_skill(
            db,
            request=_request(),
            actor=actor,
            workspace=workspace,
            membership=membership,
            payload=SkillCreateRequest(
                name="platform-guidance",
                description="Shared guidance.",
                instructions="Follow the shared workflow.",
                scope=SkillScope.PLATFORM,
            ),
        )

    db.commit.assert_awaited_once_with()
    platform_write.assert_not_awaited()


async def test_platform_update_stops_before_maintenance_write_when_request_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("services.skills.update_skill")
    actor, workspace, membership, skill = _platform_context(monkeypatch)
    db = AsyncMock(spec=AsyncSession)
    db.scalar.return_value = skill
    db.commit.side_effect = RuntimeError("request commit failed")
    platform_write = AsyncMock()
    monkeypatch.setattr(module, "_update_platform_skill", platform_write)

    with pytest.raises(RuntimeError, match="request commit failed"):
        await module.update_skill(
            db,
            request=_request(),
            actor=actor,
            workspace=workspace,
            membership=membership,
            skill_id=skill.id,
            payload=SkillUpdateRequest(description="Updated guidance."),
        )

    db.commit.assert_awaited_once_with()
    platform_write.assert_not_awaited()


async def test_platform_delete_stops_before_maintenance_write_when_request_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("services.skills.delete_skill")
    actor, workspace, membership, skill = _platform_context(monkeypatch)
    db = AsyncMock(spec=AsyncSession)
    db.scalar.return_value = skill
    db.commit.side_effect = RuntimeError("request commit failed")
    platform_write = AsyncMock()
    monkeypatch.setattr(module, "_delete_platform_skill", platform_write)

    with pytest.raises(RuntimeError, match="request commit failed"):
        await module.delete_skill(
            db,
            request=_request(),
            actor=actor,
            workspace=workspace,
            membership=membership,
            skill_id=skill.id,
        )

    db.commit.assert_awaited_once_with()
    platform_write.assert_not_awaited()
