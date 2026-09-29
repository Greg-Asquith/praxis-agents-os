"""Skill-writing runtime tools stay inside the workspace and the user's role."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import maintenance_async_db_session
from models.audit_event import AuditEvent
from models.skills import Skill
from models.workspace import WorkspaceRole
from services.agents.runtime.tools.skill_authoring import create_skill, read_skill, update_skill
from tests.factories import build_skill, build_user, build_workspace, build_workspace_membership
from utils.content import ContentScope

pytestmark = pytest.mark.asyncio


async def _context(db: AsyncSession, *, role: WorkspaceRole = WorkspaceRole.MEMBER):
    suffix = uuid4().hex
    user = build_user(email=f"skill-tools-{suffix}@example.com")
    workspace = build_workspace(slug=f"skill-tools-{suffix[:12]}")
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=role,
    )
    db.add_all([user, workspace, membership])
    await db.flush()
    deps = SimpleNamespace(db=db, user=user, workspace=workspace, membership=membership)
    return SimpleNamespace(deps=deps)


async def test_create_skill_saves_an_unshared_workspace_skill_audited_to_the_user(
    db_session: AsyncSession,
) -> None:
    ctx = await _context(db_session)

    result = await create_skill(
        ctx,
        name="weekly-client-report",
        human_name="Weekly client report",
        description="Use when writing the weekly client report.",
        instructions="1. Gather the week's results.",
        share_with_all_workspaces=False,
    )

    skill = await db_session.scalar(
        select(Skill).where(
            Skill.workspace_id == ctx.deps.workspace.id,
            Skill.name == "weekly-client-report",
        )
    )
    assert result["status"] == "created"
    assert skill is not None
    assert skill.scope == ContentScope.WORKSPACE
    assert skill.created_by == ctx.deps.user.id
    assert skill.documentation_refs == {}
    audit = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.resource_id == str(skill.id))
    )
    assert audit is not None
    assert audit.actor_user_id == ctx.deps.user.id


async def test_read_only_member_cannot_create_a_skill(db_session: AsyncSession) -> None:
    ctx = await _context(db_session, role=WorkspaceRole.READ_ONLY)

    with pytest.raises(ModelRetry, match="write access"):
        await create_skill(
            ctx,
            name="blocked-skill",
            human_name="Blocked",
            description="Never saved.",
            instructions="Never saved.",
            share_with_all_workspaces=False,
        )

    assert (
        await db_session.scalar(select(Skill).where(Skill.workspace_id == ctx.deps.workspace.id))
        is None
    )


async def test_update_skill_replaces_only_the_supplied_fields(db_session: AsyncSession) -> None:
    ctx = await _context(db_session)
    skill = build_skill(
        workspace=ctx.deps.workspace,
        created_by=ctx.deps.user,
        name="triage",
        description="Original description.",
        instructions="Original steps.",
    )
    db_session.add(skill)
    await db_session.flush()

    await update_skill(ctx, name="triage", instructions="Revised steps.")

    await db_session.refresh(skill)
    assert skill.instructions == "Revised steps."
    assert skill.description == "Original description."


async def test_update_skill_refuses_others_shared_skills_and_other_workspaces(
    db_session: AsyncSession,
) -> None:
    suffix = uuid4().hex
    other_user = build_user(email=f"skill-tools-other-{suffix}@example.com")
    other_workspace = build_workspace(slug=f"skill-tools-other-{suffix[:12]}")
    platform_skill = build_skill(
        workspace=other_workspace,
        created_by=other_user,
        name=f"platform-{suffix[:8]}",
        scope=ContentScope.PLATFORM,
        workspace_id=None,
        instructions="Platform steps.",
    )
    foreign_skill = build_skill(
        workspace=other_workspace,
        created_by=other_user,
        name=f"foreign-{suffix[:8]}",
        instructions="Foreign steps.",
    )
    async with maintenance_async_db_session() as maintenance:
        maintenance.add_all([other_user, other_workspace])
        await maintenance.flush()
        maintenance.add_all([platform_skill, foreign_skill])
    ctx = await _context(db_session)

    with pytest.raises(ModelRetry, match="Only the person who shared"):
        await update_skill(ctx, name=platform_skill.name, instructions="Hijacked.")
    with pytest.raises(ModelRetry, match="No skill named"):
        await update_skill(ctx, name=foreign_skill.name, instructions="Hijacked.")
    with pytest.raises(ModelRetry, match="No skill named"):
        await read_skill(ctx, name=foreign_skill.name)

    async with maintenance_async_db_session() as maintenance:
        instructions = set(
            await maintenance.scalars(
                select(Skill.instructions).where(
                    Skill.id.in_([platform_skill.id, foreign_skill.id])
                )
            )
        )
    assert instructions == {"Platform steps.", "Foreign steps."}
