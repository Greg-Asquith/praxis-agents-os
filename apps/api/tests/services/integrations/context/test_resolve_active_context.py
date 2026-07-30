# apps/api/tests/services/integrations/context/test_resolve_active_context.py

"""Database-backed active-context resolution tests."""

from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent, AgentSchedule, AgentScheduleRun
from models.agent_run import AgentRun
from models.conversation import Conversation
from services.agent_runs.domain import (
    RUN_TRIGGER_DELEGATED,
    RUN_TRIGGER_INTERACTIVE,
    RUN_TRIGGER_SCHEDULED,
)
from services.integrations.context.resolve_active_context import resolve_active_context
from tests.factories import (
    build_active_context_selection,
    build_external_credential,
    build_integration_connection,
    build_integration_context_group,
    build_integration_resource,
)


async def _agent(db: AsyncSession, data: dict[str, object]) -> Agent:
    agent = Agent(
        name="Context Agent",
        slug=f"context-agent-{uuid4().hex[:8]}",
        instructions="Use context.",
        workspace_id=data["workspace"].id,
        created_by=data["user"].id,
    )
    db.add(agent)
    await db.flush()
    return agent


async def _run(
    db: AsyncSession,
    data: dict[str, object],
    agent: Agent,
    *,
    trigger: str = RUN_TRIGGER_INTERACTIVE,
    parent: AgentRun | None = None,
    conversation: Conversation | None = None,
) -> AgentRun:
    run = AgentRun(
        conversation_id=(conversation or data["conversation"]).id,
        agent_id=agent.id,
        workspace_id=data["workspace"].id,
        user_id=data["user"].id,
        trigger=trigger,
        status="pending",
        parent_run_id=parent.id if parent is not None else None,
        delegation_depth=(parent.delegation_depth or 0) + 1 if parent is not None else 0,
    )
    db.add(run)
    await db.flush()
    return run


async def test_single_resource_selection_resolves_and_fails_closed_for_write(
    db_session: AsyncSession,
    context_data: dict[str, object],
) -> None:
    agent = await _agent(db_session, context_data)
    run = await _run(db_session, context_data, agent)
    db_session.add(
        build_active_context_selection(
            workspace=context_data["workspace"],
            conversation=context_data["conversation"],
            resource=context_data["first"],
        )
    )
    await db_session.flush()

    resolved = await resolve_active_context(
        db_session,
        run=run,
        user=context_data["user"],
        workspace=context_data["workspace"],
    )

    assert resolved.source == "conversation"
    assert [entry.display_name for entry in resolved.entries] == ["First resource"]
    assert resolved.entries[0].write_allowed is False


@pytest.mark.parametrize(
    ("resource_overrides", "connection_status", "reason"),
    [
        ({"enabled": False}, "active", "resource_disabled"),
        ({"availability": "removed"}, "active", "resource_removed"),
        ({}, "needs_reauth", "connection_needs_reauth"),
        ({}, "needs_credential", "connection_needs_credential"),
        ({}, "revoked", "connection_revoked"),
        ({}, "error", "connection_error"),
        ({}, "discovery_pending", "connection_inactive"),
    ],
)
async def test_unavailable_resource_and_connection_states_are_reported(
    db_session: AsyncSession,
    context_data: dict[str, object],
    resource_overrides: dict[str, object],
    connection_status: str,
    reason: str,
) -> None:
    agent = await _agent(db_session, context_data)
    run = await _run(db_session, context_data, agent)
    resource = context_data["first"]
    for key, value in resource_overrides.items():
        setattr(resource, key, value)
    context_data["connection"].status = connection_status
    db_session.add(
        build_active_context_selection(
            workspace=context_data["workspace"],
            conversation=context_data["conversation"],
            resource=resource,
        )
    )
    await db_session.flush()

    resolved = await resolve_active_context(
        db_session,
        run=run,
        user=context_data["user"],
        workspace=context_data["workspace"],
    )

    assert not resolved.entries
    assert [item.reason for item in resolved.unavailable] == [reason]


async def test_group_spans_connections_and_deduplicates_newest_active_resource(
    db_session: AsyncSession,
    context_data: dict[str, object],
) -> None:
    agent = await _agent(db_session, context_data)
    run = await _run(db_session, context_data, agent)
    credential = build_external_credential(principal_fingerprint=uuid4().hex.ljust(64, "0"))
    db_session.add(credential)
    await db_session.flush()
    newer_connection = build_integration_connection(
        credential=credential,
        user=context_data["user"],
        workspace=context_data["workspace"],
        status="active",
        created_at=datetime.now(UTC) + timedelta(seconds=1),
        label="New connection",
    )
    db_session.add(newer_connection)
    await db_session.flush()
    duplicate = build_integration_resource(
        connection=newer_connection,
        external_id=context_data["first"].external_id,
        display_name="New duplicate",
        enabled=True,
        writable=True,
        permissions_metadata={"role": "editor"},
    )
    distinct = build_integration_resource(
        connection=newer_connection,
        external_id="third",
        display_name="Third resource",
        enabled=True,
    )
    db_session.add_all([duplicate, distinct])
    await db_session.flush()
    group = build_integration_context_group(
        workspace=context_data["workspace"],
        user=context_data["user"],
        resources=[context_data["first"], duplicate, distinct],
    )
    db_session.add(group)
    await db_session.flush()
    db_session.add(
        build_active_context_selection(
            workspace=context_data["workspace"],
            conversation=context_data["conversation"],
            group=group,
        )
    )
    await db_session.flush()

    resolved = await resolve_active_context(
        db_session,
        run=run,
        user=context_data["user"],
        workspace=context_data["workspace"],
    )

    assert {entry.display_name for entry in resolved.entries} == {
        "New duplicate",
        "Third resource",
    }
    assert next(entry for entry in resolved.entries if entry.external_id == "first").write_allowed


async def test_degraded_connection_is_usable(
    db_session: AsyncSession,
    context_data: dict[str, object],
) -> None:
    agent = await _agent(db_session, context_data)
    run = await _run(db_session, context_data, agent)
    context_data["connection"].status = "degraded"
    db_session.add(
        build_active_context_selection(
            workspace=context_data["workspace"],
            conversation=context_data["conversation"],
            resource=context_data["first"],
        )
    )
    await db_session.flush()

    resolved = await resolve_active_context(
        db_session,
        run=run,
        user=context_data["user"],
        workspace=context_data["workspace"],
    )

    assert resolved.entries[0].connection_status == "degraded"


async def test_deleted_group_degrades_to_dangling(
    db_session: AsyncSession,
    context_data: dict[str, object],
) -> None:
    agent = await _agent(db_session, context_data)
    run = await _run(db_session, context_data, agent)
    group = build_integration_context_group(
        workspace=context_data["workspace"],
        user=context_data["user"],
        resources=[context_data["first"]],
    )
    db_session.add(group)
    await db_session.flush()
    db_session.add(
        build_active_context_selection(
            workspace=context_data["workspace"],
            conversation=context_data["conversation"],
            group=group,
        )
    )
    group.soft_delete(deleted_by=context_data["user"].id, cascade=False)
    await db_session.flush()

    resolved = await resolve_active_context(
        db_session,
        run=run,
        user=context_data["user"],
        workspace=context_data["workspace"],
    )

    assert resolved.unavailable[0].reason == "dangling"


async def test_scheduled_and_delegated_runs_use_schedule_context(
    db_session: AsyncSession,
    context_data: dict[str, object],
) -> None:
    agent = await _agent(db_session, context_data)
    root = await _run(db_session, context_data, agent, trigger=RUN_TRIGGER_SCHEDULED)
    schedule = AgentSchedule(
        agent_id=agent.id,
        user_id=context_data["user"].id,
        workspace_id=context_data["workspace"].id,
        schedule_type="interval",
        interval_minutes=15,
        active_context={
            "type": "resource",
            "integration_resource_id": str(context_data["second"].id),
        },
    )
    db_session.add(schedule)
    await db_session.flush()
    db_session.add(
        AgentScheduleRun(
            schedule_id=schedule.id,
            workspace_id=context_data["workspace"].id,
            user_id=context_data["user"].id,
            agent_id=agent.id,
            scheduled_for=datetime.now(UTC),
            status="running",
            agent_run_id=root.id,
        )
    )
    await db_session.flush()
    child_conversation = Conversation(
        user_id=context_data["user"].id,
        workspace_id=context_data["workspace"].id,
        created_by=context_data["user"].id,
        active_agent_id=agent.id,
        source="delegated",
    )
    db_session.add(child_conversation)
    await db_session.flush()
    child = await _run(
        db_session,
        context_data,
        agent,
        trigger=RUN_TRIGGER_DELEGATED,
        parent=root,
        conversation=child_conversation,
    )

    root_context = await resolve_active_context(
        db_session,
        run=root,
        user=context_data["user"],
        workspace=context_data["workspace"],
    )
    child_context = await resolve_active_context(
        db_session,
        run=child,
        user=context_data["user"],
        workspace=context_data["workspace"],
    )

    assert root_context.source == child_context.source == "schedule"
    assert root_context.entries == child_context.entries
    assert root_context.entries[0].display_name == "Second resource"


async def test_malformed_schedule_context_is_ignored(
    db_session: AsyncSession,
    context_data: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[str] = []
    module = import_module("services.integrations.context.resolve_active_context")
    monkeypatch.setattr(
        module.logger, "warning", lambda message, **_kwargs: warnings.append(message)
    )
    agent = await _agent(db_session, context_data)
    run = await _run(db_session, context_data, agent, trigger=RUN_TRIGGER_SCHEDULED)
    schedule = AgentSchedule(
        agent_id=agent.id,
        user_id=context_data["user"].id,
        workspace_id=context_data["workspace"].id,
        schedule_type="interval",
        interval_minutes=15,
        active_context={"type": "resource"},
    )
    db_session.add(schedule)
    await db_session.flush()
    db_session.add(
        AgentScheduleRun(
            schedule_id=schedule.id,
            workspace_id=context_data["workspace"].id,
            user_id=context_data["user"].id,
            agent_id=agent.id,
            scheduled_for=datetime.now(UTC),
            status="running",
            agent_run_id=run.id,
        )
    )
    await db_session.flush()

    resolved = await resolve_active_context(
        db_session,
        run=run,
        user=context_data["user"],
        workspace=context_data["workspace"],
    )

    assert resolved.is_empty
    assert warnings == ["Ignoring malformed scheduled active context"]
