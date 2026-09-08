# apps/api/tests/scenarios/test_approval_continuation.py

"""Durable approval acceptance and worker handoff through the public service."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from core.exceptions.general import ConflictError
from models.agent_run import AgentRun
from models.audit_event import AuditEvent
from models.user import User
from models.workspace import Workspace
from services.agent_runs.claim_approval_continuation import claim_approval_continuation
from services.agent_runs.continuation_state import CONTINUATION_KEY, load_approval_continuation
from services.agent_runs.get_approval_state import get_agent_run_approval_state
from services.agent_runs.resume_run_stream import resume_agent_run_stream
from services.agent_runs.schemas import AgentRunResumeDecision, AgentRunResumeRequest
from services.agents.runtime.run_manager import run_task_registry
from tests.support.delegation import scenario_effects
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    add_scenario_delegate,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)


@pytest.mark.parametrize("handoff_failure", [False, True])
async def test_accepted_decisions_survive_handoff_and_execute_once(
    committed_db_session_factory, monkeypatch, handoff_failure
):
    factory = committed_db_session_factory
    with scenario_effects() as effects:
        context = await build_scenario_agent(
            factory,
            tool_names=[effects.name],
            trigger="scheduled",
            metadata={"envelope": {"side_effect_policy": "require_approval"}},
        )
        model = scripted_model(
            turns=[
                ToolTurn((ToolCall(effects.name, {"value": "approved once"}, "write"),)),
                "Finished.",
            ]
        )
        monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: model)
        parked = await run_scenario(factory, context, model=model)
        assert parked.run.status == "awaiting_approval"
        queued = []

        def capture(_run_id, coroutine, **_kwargs):
            queued.append(coroutine)
            if handoff_failure:
                coroutine.close()
                raise RuntimeError("Response delivery failed")

        monkeypatch.setattr(run_task_registry, "spawn", capture)
        async with factory() as db:
            actor = await db.get(User, context.user_id)
            workspace = await db.get(Workspace, context.workspace_id)
            projection = await get_agent_run_approval_state(
                db, actor=actor, workspace=workspace, run_id=context.run_id
            )
            payload = AgentRunResumeRequest(
                approval_revision=projection.approval_revision,
                decisions=[
                    AgentRunResumeDecision(
                        tool_call_id="write",
                        approval_id=projection.approvals[0].approval_id,
                        decision="approved",
                    )
                ],
            )
        barrier = asyncio.Barrier(2)

        async def submit(value=payload):
            async with factory() as db:
                return await resume_agent_run_stream(
                    db, actor=actor, workspace=workspace, run_id=context.run_id, payload=value
                )

        async def simultaneous():
            await barrier.wait()
            return await submit()

        try:
            attempts = await asyncio.gather(simultaneous(), simultaneous(), return_exceptions=True)
            assert len(queued) == 1
            conflicts = [item for item in attempts if isinstance(item, ConflictError)]
            assert len(conflicts) == 1
            assert conflicts[0].details["code"] == "approval_already_reserved"
            changed = payload.model_copy(
                update={
                    "decisions": [payload.decisions[0].model_copy(update={"decision": "denied"})]
                }
            )
            with pytest.raises(ConflictError) as error:
                await submit(changed)
            assert error.value.details["code"] == "approval_decisions_conflict"
            assert error.value.details["decisions_accepted"] is False
            async with factory() as db:
                root = await db.get(AgentRun, context.run_id)
                reservation = load_approval_continuation(root)
                assert root.status == "running"
                assert reservation.phase == "reserved"
                assert reservation.deferred_tool_results["approvals"]["write"]
                accepted = list(
                    await db.scalars(
                        select(AuditEvent).where(
                            AuditEvent.resource_id == str(root.id),
                            AuditEvent.details["operation"].astext == "approval_accepted",
                        )
                    )
                )
                assert len(accepted) == 1
            assert effects.calls == []
            if handoff_failure:
                async with factory() as db:
                    root = await db.get(AgentRun, context.run_id)
                    root.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
                    await db.commit()
                from services.agent_runs.reap_abandoned import reap_abandoned_runs

                async with factory() as db:
                    await reap_abandoned_runs(db, conversation_id=context.conversation_id)
                    await db.commit()
                    root = await db.get(AgentRun, context.run_id)
                    assert root.outcome == "blocked"
                    assert root.error_code == "agent_run_resume_requires_recovery"
                    assert CONTINUATION_KEY not in (root.metadata_json or {})
                    assert root.completion_json["recovery"]["actions"]
                assert effects.calls == []
            else:
                await queued[0]
                async with factory() as db:
                    root = await db.get(AgentRun, context.run_id)
                    assert root.status == "completed"
                    assert CONTINUATION_KEY not in (root.metadata_json or {})
                assert effects.calls == [(context.run_id, "approved once")]
        finally:
            for coroutine in queued:
                coroutine.close()


async def test_continuation_claim_is_consumed_before_execution(
    committed_db_session_factory, monkeypatch
):
    factory = committed_db_session_factory
    with scenario_effects() as effects:
        context = await build_scenario_agent(
            factory,
            tool_names=[effects.name],
            trigger="scheduled",
            metadata={"envelope": {"side_effect_policy": "require_approval"}},
        )
        await run_scenario(
            factory,
            context,
            model=scripted_model(
                turns=[
                    ToolTurn((ToolCall(effects.name, {"value": "reserved"}, "write"),)),
                ]
            ),
        )
        monkeypatch.setattr(
            run_task_registry, "spawn", lambda _id, coroutine, **_kw: coroutine.close()
        )
        async with factory() as db:
            actor = await db.get(User, context.user_id)
            workspace = await db.get(Workspace, context.workspace_id)
            projection = await get_agent_run_approval_state(
                db, actor=actor, workspace=workspace, run_id=context.run_id
            )
            await resume_agent_run_stream(
                db,
                actor=actor,
                workspace=workspace,
                run_id=context.run_id,
                payload=AgentRunResumeRequest(
                    approval_revision=projection.approval_revision,
                    decisions=[
                        AgentRunResumeDecision(
                            tool_call_id="write",
                            approval_id=projection.approvals[0].approval_id,
                            decision="approved",
                        )
                    ],
                ),
            )
            run = await db.get(AgentRun, context.run_id)
            owner = run.owner_instance_id
        async with factory() as db:
            assert (
                await claim_approval_continuation(
                    db, run_id=context.run_id, owner_instance_id=owner
                )
                is not None
            )
        async with factory() as db:
            assert (
                await claim_approval_continuation(
                    db, run_id=context.run_id, owner_instance_id=owner
                )
                is None
            )
            run = await db.get(AgentRun, context.run_id)
            assert run.status == "running"
        assert effects.calls == []


@pytest.mark.parametrize("child_status", ["completed", "failed", "cancelled", "missing"])
async def test_unavailable_child_stops_public_resume_without_replacement(
    committed_db_session_factory, monkeypatch, child_status
):
    from services.agents.runtime.entity_references.domain import AgentReference

    factory = committed_db_session_factory
    with scenario_effects() as effects:
        context = await build_scenario_agent(
            factory,
            trigger="scheduled",
            metadata={"envelope": {"side_effect_policy": "require_approval"}},
        )
        specialist = await add_scenario_delegate(factory, context, tool_names=[effects.name])
        model = scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            "delegate_to_agent",
                            {
                                "agent_id": AgentReference(
                                    entity_id=str(specialist.id), label=specialist.name
                                ).model_dump(mode="json"),
                                "task": "Perform the reviewed action.",
                            },
                            "delegate",
                        ),
                    )
                ),
                ToolTurn((ToolCall(effects.name, {"value": "review"}, "write"),)),
            ]
        )
        monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: model)
        await run_scenario(factory, context, model=model)
        async with factory() as db:
            actor = await db.get(User, context.user_id)
            workspace = await db.get(Workspace, context.workspace_id)
            projection = await get_agent_run_approval_state(
                db, actor=actor, workspace=workspace, run_id=context.run_id
            )
            child = await db.scalar(
                select(AgentRun).where(AgentRun.parent_run_id == context.run_id)
            )
            child_id = child.id
            if child_status == "missing":
                child.deleted = True
            else:
                child.status = child_status
            await db.commit()
            with pytest.raises(ConflictError) as error:
                await resume_agent_run_stream(
                    db,
                    actor=actor,
                    workspace=workspace,
                    run_id=context.run_id,
                    payload=AgentRunResumeRequest(
                        approval_revision=projection.approval_revision,
                        decisions=[
                            AgentRunResumeDecision(
                                tool_call_id="write",
                                approval_id=projection.approvals[0].approval_id,
                                decision="approved",
                            )
                        ],
                    ),
                )
            assert error.value.details["code"] == "agent_run_resume_requires_recovery"
        async with factory() as db:
            root = await db.get(AgentRun, context.run_id)
            assert root.status == "failed"
            assert root.outcome == "blocked"
            assert root.completion_json["recovery"]
            children = list(
                await db.scalars(select(AgentRun).where(AgentRun.parent_run_id == root.id))
            )
            assert [child.id for child in children] == [child_id]
            assert children[0].status == (
                "awaiting_approval" if child_status == "missing" else child_status
            )
        assert effects.calls == []
