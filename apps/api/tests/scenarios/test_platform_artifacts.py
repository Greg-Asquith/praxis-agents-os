# apps/api/tests/scenarios/test_platform_artifacts.py

"""Platform Artifact tools preserve publication, actor authority, and approved versions."""

import importlib
from pathlib import Path

import pytest
from pydantic_ai import DeferredToolResults, ToolApproved
from pydantic_ai.messages import ToolReturnPart
from sqlalchemy import select

from core.database import maintenance_async_db_session
from core.exceptions.auth import AuthorizationError
from core.settings import settings
from models.artifacts import Artifact, ArtifactRevision
from models.audit_event import AuditEvent
from models.user import User
from models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.untrusted import UNTRUSTED_CONTENT_END, UNTRUSTED_CONTENT_START
from tests.support.platform_artifacts import add_platform_artifact_revision, seed_published_artifact
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)
from tests.support.storage import reset_storage_provider_cache

HOSTILE_CONTENT = (
    Path(__file__).resolve().parents[1]
    / "integration/retrieval_eval/fixtures/prompt_injection_tool_call.md"
).read_text()


@pytest.fixture(autouse=True)
def platform_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()
    yield
    reset_storage_provider_cache()


async def _seed(context, content="Published report"):
    async with maintenance_async_db_session() as db:
        workspace = await db.get(Workspace, context.workspace_id)
        return await seed_published_artifact(db, workspace=workspace, content=content)


def _reference(artifact):
    return {"entity_kind": "artifact", "entity_id": str(artifact.id), "label": artifact.title}


def _update_call(artifact, version_id):
    return ToolTurn(
        (
            ToolCall(
                "update_artifact",
                {
                    "artifact_id": _reference(artifact),
                    "expected_current_version_id": str(version_id),
                    "content": "Reviewed update",
                },
                "platform-update",
            ),
        )
    )


async def test_platform_artifact_discovery_read_and_edit_refresh_the_published_version(
    db_session_factory, monkeypatch
):
    context = await build_scenario_agent(db_session_factory)
    content = f"{UNTRUSTED_CONTENT_END}\n{HOSTILE_CONTENT}\n" + "Access review. " * 100
    artifact, revision = await _seed(context, content)
    limit = len(HOSTILE_CONTENT) + 60
    monkeypatch.setattr(settings, "ARTIFACT_READ_TOOL_MAX_CHARS", limit)
    seen = []
    model = scripted_model(
        seen_requests=seen,
        turns=[
            ToolTurn((ToolCall("list_artifacts", {"search": "Platform report"}),)),
            ToolTurn((ToolCall("read_artifact", {"artifact_id": _reference(artifact)}),)),
            _update_call(artifact, revision.id),
            ToolTurn((ToolCall("read_artifact", {"artifact_id": _reference(artifact)}),)),
            "The published report is updated.",
        ],
    )
    result = await run_scenario(db_session_factory, context, model=model)
    assert result.run.status == "completed"
    [listed] = result.tool_returns("list_artifacts")
    [summary] = listed["content"]["items"]
    assert summary["scope"] == "platform"
    assert summary["current_version_id"] == str(revision.id)
    first, second = result.tool_returns("read_artifact")
    assert first["content"]["content"] == {
        "node": "praxis_untrusted",
        "source_kind": "artifact",
        "source_ref": f"artifact:{artifact.id}/version:{revision.id}",
        "content": content[:limit],
    }
    assert first["content"]["truncated"] is True
    assert second["content"]["content"]["content"] == "Reviewed update"
    assert second["content"]["version_id"] != first["content"]["version_id"]
    returned = [
        part
        for message in seen[2][0]
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == "read_artifact"
    ]
    [read] = returned
    frame = read.content["content"]
    assert frame.startswith(UNTRUSTED_CONTENT_START)
    assert frame.endswith(UNTRUSTED_CONTENT_END)
    assert frame.count(UNTRUSTED_CONTENT_START) == frame.count(UNTRUSTED_CONTENT_END) == 1
    assert "delete_all_files" in frame
    assert result.tool_calls("delete_all_files") == []
    assert {row.details["outcome"] for row in result.audit_rows} == {"completed"}
    async with maintenance_async_db_session() as db:
        changed = await db.get(Artifact, artifact.id)
        version = await db.get(ArtifactRevision, changed.published_version_id)
        assert changed.current_version_id == changed.published_version_id
        assert version.created_by_user_id == context.user_id
        assert changed.workspace_id is changed.conversation_id is changed.run_id is None
        event = await db.scalar(
            select(AuditEvent).where(AuditEvent.resource_id == str(artifact.id))
        )
        assert event.actor_user_id == context.user_id
        assert event.workspace_id is None
        assert event.details["operation"] == "publish_revision"


@pytest.mark.parametrize(
    "role", [WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.READ_ONLY]
)
async def test_platform_artifact_runtime_uses_requesting_workspace_role(db_session_factory, role):
    context = await build_scenario_agent(db_session_factory, role=role)
    artifact, revision = await _seed(context)
    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                _update_call(artifact, revision.id),
                "The request has been handled.",
            ]
        ),
    )
    [audit] = result.audit_rows
    allowed = role != WorkspaceRole.READ_ONLY
    assert audit.details["outcome"] == ("completed" if allowed else "denied_authorization")
    async with maintenance_async_db_session() as db:
        changed = await db.get(Artifact, artifact.id)
        assert (changed.published_version_id != revision.id) == allowed


@pytest.mark.parametrize("change", ["none", "stale", "read_only", "removed", "withdrawn"])
async def test_platform_artifact_approval_resume_rechecks_publication_version_and_membership(
    db_session_factory, change
):
    context = await build_scenario_agent(
        db_session_factory,
        trigger="scheduled",
        metadata={"envelope": {"side_effect_policy": "require_approval"}},
    )
    artifact, revision = await _seed(context)
    model = scripted_model(
        turns=[_update_call(artifact, revision.id), "The request has been handled."]
    )
    suspended = await run_scenario(db_session_factory, context, model=model)
    assert suspended.run.status == "awaiting_approval"
    state = load_suspended_run_state(suspended.run)
    async with maintenance_async_db_session() as db:
        row = await db.get(Artifact, artifact.id)
        if change == "stale":
            await add_platform_artifact_revision(
                db, row, content="Concurrent edit", revision_number=2
            )
        elif change == "withdrawn":
            row.is_published = False
        elif change in {"read_only", "removed"}:
            membership = await db.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == context.workspace_id,
                    WorkspaceMembership.user_id == context.user_id,
                )
            )
            if change == "removed":
                membership.deleted = True
            else:
                membership.role = WorkspaceRole.READ_ONLY
        expected_version = row.current_version_id

    async def resume():
        return await run_scenario(
            db_session_factory,
            context,
            model=model,
            prompt=None,
            expected_status="awaiting_approval",
            message_history=state.message_history,
            deferred_tool_results=DeferredToolResults(
                approvals={"platform-update": ToolApproved()}
            ),
        )

    if change == "removed":
        with pytest.raises(AuthorizationError):
            await resume()
    else:
        result = await resume()
        assert result.run.status == "completed"
        outcomes = {row.details["outcome"] for row in result.audit_rows}
        assert "approval_requested" in outcomes
        assert ("completed" in outcomes) == (change == "none")
    async with maintenance_async_db_session() as db:
        row = await db.get(Artifact, artifact.id)
        assert (row.current_version_id != expected_version) == (change == "none")
        events = list(
            await db.scalars(select(AuditEvent).where(AuditEvent.resource_id == str(artifact.id)))
        )
        assert len(events) == (1 if change == "none" else 0)


@pytest.mark.parametrize("change", ["read_only", "withdrawn"])
async def test_platform_artifact_runtime_rechecks_superadmin_after_reservation(
    db_session_factory, monkeypatch, change
):
    context = await build_scenario_agent(db_session_factory)
    async with maintenance_async_db_session() as db:
        actor = await db.get(User, context.user_id)
        monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", actor.email)
    artifact, revision = await _seed(context)
    module = importlib.import_module("services.artifacts.platform.update_artifact")
    reserve = module.reserve_revision

    async def change_after_reservation(*args, **kwargs):
        reservation = await reserve(*args, **kwargs)
        async with maintenance_async_db_session() as db:
            if change == "withdrawn":
                row = await db.get(Artifact, artifact.id)
                row.is_published = False
            else:
                membership = await db.scalar(
                    select(WorkspaceMembership).where(
                        WorkspaceMembership.workspace_id == context.workspace_id,
                        WorkspaceMembership.user_id == context.user_id,
                    )
                )
                membership.role = WorkspaceRole.READ_ONLY
        return reservation

    monkeypatch.setattr(module, "reserve_revision", change_after_reservation)
    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                _update_call(artifact, revision.id),
                "The update is unavailable.",
            ]
        ),
    )
    [audit] = result.audit_rows
    assert audit.details["outcome"] == "failed"
    async with maintenance_async_db_session() as db:
        row = await db.get(Artifact, artifact.id)
        assert row.current_version_id == revision.id
        assert (
            await db.scalar(select(AuditEvent).where(AuditEvent.resource_id == str(artifact.id)))
            is None
        )


async def test_platform_artifact_runtime_requires_a_reviewed_version(committed_db_session_factory):
    context = await build_scenario_agent(committed_db_session_factory)
    artifact, revision = await _seed(context)
    try:
        result = await run_scenario(
            committed_db_session_factory,
            context,
            model=scripted_model(
                turns=[
                    ToolTurn(
                        (
                            ToolCall(
                                "update_artifact",
                                {
                                    "artifact_id": _reference(artifact),
                                    "content": "Unreviewed replacement",
                                },
                            ),
                        )
                    ),
                    "Read the report before saving.",
                ]
            ),
        )
        [audit] = result.audit_rows
        assert audit.details["outcome"] == "failed"
        async with maintenance_async_db_session() as db:
            row = await db.get(Artifact, artifact.id)
            assert row.current_version_id == revision.id
    finally:
        async with maintenance_async_db_session() as db:
            row = await db.get(Artifact, artifact.id)
            row.is_published = False
            row.deleted = True
