# apps/api/tests/routes/agent_runs/test_resume_root_owner.py

"""Approval mutations belong to the verified main conversation."""

from copy import deepcopy

import pytest
from sqlalchemy import select

from core.auth.sessions import session_manager
from models.agent_run import AgentRun
from models.user import User
from models.workspace import Workspace
from services.agents.runtime.entity_references.domain import AgentReference
from tests.support.auth import bearer_headers
from tests.support.delegation import scenario_effects
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    add_scenario_delegate,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)


@pytest.mark.parametrize("parent_status", ["awaiting_approval", "running"])
async def test_child_resume_is_rejected_before_decisions_or_effects(
    committed_db_session_factory, async_client, monkeypatch, parent_status
):
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
                                "task": "Perform the write.",
                            },
                            "delegate",
                        ),
                    )
                ),
                ToolTurn((ToolCall(effects.name, {"value": "review"}, "write"),)),
            ]
        )
        monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: model)
        result = await run_scenario(factory, context, model=model)
        assert result.run.status == "awaiting_approval"
        async with factory() as db:
            root = await db.get(AgentRun, context.run_id)
            child = await db.scalar(select(AgentRun).where(AgentRun.parent_run_id == root.id))
            actor = await db.get(User, context.user_id)
            workspace = await db.get(Workspace, context.workspace_id)
            if parent_status == "running":
                from services.agent_runs.start_with_lease import start_agent_run_with_lease

                await start_agent_run_with_lease(db, root)
            session = await session_manager.create_session(db, str(actor.id))
            await db.commit()
            before = deepcopy(child.metadata_json)
            root_before = deepcopy(root.metadata_json)
            child_id = child.id
            headers = {**bearer_headers(session["session_token"]), "X-Workspace": workspace.slug}
        response = await async_client.post(
            f"/api/v1/agent-runs/{child_id}/resume",
            headers=headers,
            json={"decisions": [{"tool_call_id": "write", "decision": "approved"}]},
        )
        assert response.status_code == 409
        problem = response.json()
        assert problem["code"] == "delegated_run_requires_root_approval"
        assert problem["root_run_id"] == str(context.run_id)
        assert problem["root_conversation_id"] == str(context.conversation_id)
        async with factory() as db:
            child = await db.get(AgentRun, child_id)
            root = await db.get(AgentRun, context.run_id)
            assert child.status == "awaiting_approval"
            assert root.status == parent_status
            assert child.metadata_json == before
            assert root.metadata_json == root_before
        assert effects.calls == []


@pytest.mark.parametrize("generation", ["legacy", "current"])
async def test_resume_http_contract_reserves_once_and_returns_stream_version(
    committed_db_session_factory, async_client, monkeypatch, generation
):
    from uuid import uuid4

    from services.agent_runs.get_approval_state import get_agent_run_approval_state
    from services.agents.runtime.run_manager import run_task_registry
    from services.agents.runtime.stream_protocol import (
        STREAM_PROTOCOL_VERSION,
        STREAM_VERSION_HEADER,
    )
    from tests.support.approval_fixtures import restore_approval_fixture

    factory = committed_db_session_factory
    queued = []

    def disconnect(_id, coroutine, *, sink, **_kwargs):
        queued.append(coroutine)
        coroutine.close()
        sink.detach()

    monkeypatch.setattr(run_task_registry, "spawn", disconnect)
    with scenario_effects(name="scenario_release_write") as effects:
        context = await restore_approval_fixture(factory, "direct")
        async with factory() as db:
            actor = await db.get(User, context.user_id)
            workspace = await db.get(Workspace, context.workspace_id)
            root = await db.get(AgentRun, context.run_id)
            if generation == "current":
                metadata = deepcopy(root.metadata_json)
                metadata["approval_state"]["approval_batch_id"] = str(uuid4())
                root.metadata_json = metadata
            session = await session_manager.create_session(db, str(actor.id))
            await db.commit()
            projection = await get_agent_run_approval_state(
                db, actor=actor, workspace=workspace, run_id=root.id
            )
            headers = {**bearer_headers(session["session_token"]), "X-Workspace": workspace.slug}
        payload = {"decisions": [{"tool_call_id": "write", "decision": "approved"}]}
        url = f"/api/v1/agent-runs/{context.run_id}/resume"
        if generation == "current":
            stale = await async_client.post(url, headers=headers, json=payload)
            assert stale.status_code == 409
            assert stale.json()["error_code"] == "approval_refresh_required"
            assert queued == []
            payload["approval_revision"] = projection.approval_revision
            payload["decisions"][0]["approval_id"] = str(projection.approvals[0].approval_id)
        accepted = await async_client.post(url, headers=headers, json=payload)
        assert accepted.status_code == 200
        assert accepted.headers[STREAM_VERSION_HEADER] == STREAM_PROTOCOL_VERSION
        repeated = await async_client.post(url, headers=headers, json=payload)
        assert repeated.status_code == 409
        assert repeated.json()["code"] == "approval_already_reserved"
        assert repeated.json()["decisions_accepted"] is True
        conflicting = deepcopy(payload)
        conflicting["decisions"][0]["decision"] = "denied"
        rejected = await async_client.post(url, headers=headers, json=conflicting)
        assert rejected.status_code == 409
        assert rejected.json()["code"] == "approval_decisions_conflict"
        assert rejected.json()["decisions_accepted"] is False
        assert len(queued) == 1
        assert effects.calls == []
        async with factory() as db:
            root = await db.get(AgentRun, context.run_id)
            assert root.metadata_json["approval_continuation"]["phase"] == "reserved"
