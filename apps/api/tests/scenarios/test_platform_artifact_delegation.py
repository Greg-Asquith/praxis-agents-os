# apps/api/tests/scenarios/test_platform_artifact_delegation.py

"""Delegated Artifact edits retain the initiating member's live authority."""

import json
from uuid import uuid4

import pytest
from pydantic_ai.messages import RetryPromptPart, ToolReturnPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from sqlalchemy import select

from core.database import maintenance_async_db_session
from core.settings import settings
from models.agent import Agent
from models.agent_run import AgentRun
from models.artifacts import Artifact, ArtifactRevision
from models.audit_event import AuditEvent
from models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from services.agents.runtime.entity_references.domain import AgentReference, ArtifactReference
from services.artifacts.utils import artifact_revision_ref
from services.storage.factory import get_storage_provider
from tests.factories import build_user, build_workspace_membership
from tests.support.platform_artifacts import seed_published_artifact
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    add_scenario_delegate,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)
from tests.support.storage import reset_storage_provider_cache


@pytest.fixture
async def delegated_platform_artifact(committed_db_session_factory, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()
    context = await build_scenario_agent(committed_db_session_factory)
    child = await add_scenario_delegate(committed_db_session_factory, context)
    async with maintenance_async_db_session() as db:
        creator = build_user(email=f"delegate-creator-{uuid4().hex}@example.com")
        monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", creator.email)
        db.add(creator)
        db.add(
            build_workspace_membership(
                workspace_id=context.workspace_id,
                user_id=creator.id,
                role=WorkspaceRole.OWNER,
            )
        )
        saved_child = await db.get(Agent, child.id)
        saved_child.created_by = creator.id
        workspace = await db.get(Workspace, context.workspace_id)
        artifact, revision = await seed_published_artifact(db, workspace=workspace)
    try:
        yield context, child, artifact, revision
    finally:
        try:
            async with maintenance_async_db_session() as db:
                saved = await db.get(Artifact, artifact.id)
                saved.is_published = False
                saved.deleted = True
        finally:
            reset_storage_provider_cache()


@pytest.mark.parametrize("membership_change", [None, "read_only", "removed"])
async def test_platform_artifact_delegate_uses_initiating_members_live_edit_authority(
    committed_db_session_factory, delegated_platform_artifact, monkeypatch, membership_change
):
    context, child, artifact, original = delegated_platform_artifact
    reference = ArtifactReference(entity_id=artifact.id, label=artifact.title).model_dump(
        mode="json"
    )
    child_requests = []

    async def child_stream(messages, info):
        child_requests.append(list(messages))
        if len(child_requests) == 1:
            yield {
                0: DeltaToolCall(
                    name="read_artifact",
                    json_args=json.dumps({"artifact_id": reference}),
                    tool_call_id="child-read",
                )
            }
            return
        if len(child_requests) == 2:
            if membership_change is not None:
                async with maintenance_async_db_session() as db:
                    membership = await db.scalar(
                        select(WorkspaceMembership).where(
                            WorkspaceMembership.workspace_id == context.workspace_id,
                            WorkspaceMembership.user_id == context.user_id,
                        )
                    )
                    if membership_change == "removed":
                        membership.deleted = True
                    else:
                        membership.role = WorkspaceRole.READ_ONLY
            [read] = [
                part
                for message in messages
                for part in message.parts
                if isinstance(part, ToolReturnPart) and part.tool_name == "read_artifact"
            ]
            assert read.content["scope"] == "platform"
            assert read.content["version_id"] == str(original.id)
            yield {
                0: DeltaToolCall(
                    name="update_artifact",
                    json_args=json.dumps(
                        {
                            "artifact_id": reference,
                            "content": "Edited by the initiating member's delegate.",
                            "expected_current_version_id": read.content["version_id"],
                        }
                    ),
                    tool_call_id="child-update",
                )
            }
            return
        yield "Delegated edit finished."

    child_model = FunctionModel(stream_function=child_stream)
    monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: child_model)
    parent_model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        "delegate_to_agent",
                        {
                            "agent_id": AgentReference(
                                entity_id=child.id, label=child.name
                            ).model_dump(mode="json"),
                            "task": "Read and update the published platform report.",
                        },
                    ),
                )
            ),
            "The delegated task has finished.",
        ]
    )
    result = await run_scenario(committed_db_session_factory, context, model=parent_model)
    assert result.run.status == "completed"
    assert len(child_requests) == 3
    async with maintenance_async_db_session() as db:
        child_run = await db.scalar(
            select(AgentRun).where(AgentRun.parent_run_id == context.run_id)
        )
        assert child_run.status == "completed"
        assert child_run.agent_id == child.id
        assert child_run.user_id == context.user_id
        assert child_run.workspace_id == context.workspace_id
        persisted = await db.get(Artifact, artifact.id)
        revisions = list(
            await db.scalars(
                select(ArtifactRevision)
                .where(ArtifactRevision.artifact_id == artifact.id)
                .order_by(ArtifactRevision.revision_number)
            )
        )
        global_events = list(
            await db.scalars(select(AuditEvent).where(AuditEvent.resource_id == str(artifact.id)))
        )
        [invocation] = list(
            await db.scalars(
                select(AuditEvent).where(
                    AuditEvent.tool_name == "update_artifact",
                    AuditEvent.details["run_id"].astext == str(child_run.id),
                )
            )
        )
        assert invocation.actor_user_id == context.user_id
        if membership_change is not None:
            assert persisted.current_version_id == persisted.published_version_id == original.id
            assert len(revisions) == 1
            assert global_events == []
            assert invocation.status == "denied"
            assert invocation.details["outcome"] == "denied_authorization"
            assert any(
                isinstance(part, RetryPromptPart) and part.tool_name == "update_artifact"
                for message in child_requests[-1]
                for part in message.parts
            )
            return
        assert len(revisions) == 2
        saved_revision = revisions[-1]
        assert persisted.current_version_id == persisted.published_version_id == saved_revision.id
        assert saved_revision.is_published
        assert saved_revision.created_by_user_id == context.user_id
        assert saved_revision.created_by_agent_id is None
        assert invocation.status == "success"
        [event] = global_events
        assert event.workspace_id is None
        assert event.actor_user_id == context.user_id
        assert event.details["operation"] == "publish_revision"
        assert (
            await get_storage_provider().get_object(
                artifact_revision_ref(saved_revision.object_key, scope="platform")
            )
            == b"Edited by the initiating member's delegate."
        )
