"""Database-backed tests for workspace runtime tool availability."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, NotFoundError
from models.audit_event import AuditEvent
from models.workspace_tool_settings import WorkspaceToolSetting
from services.tools import get_workspace_tool_defaults, set_tool_enabled, set_tool_policy
from tests.factories import build_user, build_workspace


async def test_absent_workspace_tool_settings_default_to_allow(
    db_session: AsyncSession,
) -> None:
    workspace = build_workspace(slug=f"tool-default-{uuid4().hex[:8]}")
    db_session.add(workspace)
    await db_session.flush()

    first = await get_workspace_tool_defaults(db_session, workspace)
    second = await get_workspace_tool_defaults(db_session, workspace)

    assert first.disabled == frozenset()
    assert dict(first.policies) == {}
    assert second is first


async def test_tool_availability_upserts_invalidates_cache_and_audits(
    db_session: AsyncSession,
) -> None:
    actor = build_user(email=f"tool-settings-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"tool-settings-{uuid4().hex[:8]}")
    db_session.add_all([actor, workspace])
    await db_session.flush()

    disabled = await set_tool_enabled(
        db_session,
        workspace=workspace,
        tool_name="web_search",
        enabled=False,
        actor=actor,
        request=None,
    )
    assert disabled.enabled is False
    assert (await get_workspace_tool_defaults(db_session, workspace)).disabled == {"web_search"}

    enabled = await set_tool_enabled(
        db_session,
        workspace=workspace,
        tool_name="web_search",
        enabled=True,
        actor=actor,
        request=None,
    )
    assert enabled.enabled is True
    assert (await get_workspace_tool_defaults(db_session, workspace)).disabled == frozenset()

    settings = (
        (
            await db_session.execute(
                select(WorkspaceToolSetting).where(
                    WorkspaceToolSetting.workspace_id == workspace.id,
                    WorkspaceToolSetting.tool_name == "web_search",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(settings) == 1
    assert settings[0].enabled is True
    assert settings[0].updated_by == actor.id

    events = (
        (
            await db_session.execute(
                select(AuditEvent)
                .where(
                    AuditEvent.workspace_id == workspace.id,
                    AuditEvent.resource_type == "tool",
                    AuditEvent.resource_id == "web_search",
                )
                .order_by(AuditEvent.occurred_at)
            )
        )
        .scalars()
        .all()
    )
    assert [event.action for event in events] == ["disable", "enable"]
    assert [event.details["enabled"] for event in events] == [False, True]


async def test_tool_availability_rejects_unknown_tool(
    db_session: AsyncSession,
) -> None:
    actor = build_user(email=f"unknown-tool-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"unknown-tool-{uuid4().hex[:8]}")
    db_session.add_all([actor, workspace])
    await db_session.flush()

    with pytest.raises(NotFoundError, match="Runtime tool not found"):
        await set_tool_enabled(
            db_session,
            workspace=workspace,
            tool_name="not_a_runtime_tool",
            enabled=False,
            actor=actor,
            request=None,
        )


async def test_tool_policy_replaces_and_clears_without_enabling_a_disabled_tool(
    db_session: AsyncSession,
) -> None:
    actor = build_user(email=f"tool-policy-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"tool-policy-{uuid4().hex[:8]}")
    db_session.add_all([actor, workspace])
    await db_session.flush()

    async def set_policy(policy: str | None) -> None:
        await set_tool_policy(
            db_session,
            workspace=workspace,
            tool_name="web_search",
            policy=policy,
            actor=actor,
            request=None,
        )

    await set_tool_enabled(
        db_session,
        workspace=workspace,
        tool_name="web_search",
        enabled=False,
        actor=actor,
        request=None,
    )
    # Prime the request cache so each policy change must refresh it.
    await get_workspace_tool_defaults(db_session, workspace)

    # The settings page saves the policy before enabling, so the row must stay disabled.
    await set_policy("approval")
    defaults = await get_workspace_tool_defaults(db_session, workspace)
    assert defaults.policies == {"web_search": "approval"}
    assert defaults.disabled == {"web_search"}

    await set_policy(None)
    defaults = await get_workspace_tool_defaults(db_session, workspace)
    assert dict(defaults.policies) == {}
    assert defaults.disabled == {"web_search"}

    events = (
        await db_session.scalars(
            select(AuditEvent).where(
                AuditEvent.workspace_id == workspace.id,
                AuditEvent.action == "update",
                AuditEvent.resource_id == "web_search",
            )
        )
    ).all()
    assert {event.actor_user_id for event in events} == {actor.id}
    # Both changes happen in one transaction, so their timestamps can tie.
    assert sorted(str(event.details["policy"]) for event in events) == ["None", "approval"]

    with pytest.raises(AppValidationError, match="does not support"):
        await set_tool_policy(
            db_session,
            workspace=workspace,
            tool_name="google_ads_add_ad_group_negative_keywords",
            policy="auto",
            actor=actor,
            request=None,
        )
