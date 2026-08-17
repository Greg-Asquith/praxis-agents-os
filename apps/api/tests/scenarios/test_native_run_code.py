"""Provider-native run_code approval and scheduled-runtime scenarios."""

import json
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from pydantic_ai import DeferredToolResults, ToolApproved
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.settings import settings
from models.files import File, FileRevision
from models.workspace import Workspace
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.tools.native import run_code as run_code_tools
from services.files.append_file_revision import append_file_revision
from services.files.create_file_with_revision import create_file_with_revision
from services.files.revision_actor import FileRevisionActor
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)
from tests.support.storage import reset_storage_provider_cache


@pytest.fixture
def run_code_storage(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()
    try:
        yield
    finally:
        reset_storage_provider_cache()


def _enable_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("sk-openai-test"))


async def _create_source_file(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workspace_id: UUID,
    user_id: UUID,
) -> tuple[UUID, UUID]:
    async with session_factory() as db:
        workspace = await db.get(Workspace, workspace_id)
        assert workspace is not None
        created = await create_file_with_revision(
            db,
            workspace=workspace,
            name="budget.csv",
            content=b"month,amount\nAugust,42\n",
            content_type="text/csv",
            extension=".csv",
            actor=FileRevisionActor(user_id=user_id),
        )
        await db.commit()
        return created.file.id, created.revision.id


def _file_reference(file_id: UUID, label: str = "budget.csv") -> dict[str, object]:
    return {"entity_id": str(file_id), "entity_kind": "file", "label": label, "version": 1}


def _script_run_code(monkeypatch: pytest.MonkeyPatch, executed: list[str]) -> None:
    async def fake_execution(*, deps, task: str, inputs, model_spec, edit_target, tool_call_id):
        del deps, inputs, model_spec, edit_target, tool_call_id
        executed.append(task)
        return "The computed total is 42.", [], []

    async def fake_persistence(
        deps, *, task, captured, input_file_ids, input_revision_ids, edit_target
    ):
        del deps, task, captured, input_file_ids, input_revision_ids, edit_target
        return [], []

    monkeypatch.setattr(run_code_tools, "run_native_code_execution", fake_execution)
    monkeypatch.setattr(run_code_tools, "persist_sandbox_outputs", fake_persistence)


async def test_run_code_approval_suspends_and_resumes(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_openai(monkeypatch)
    executed: list[str] = []
    _script_run_code(monkeypatch, executed)
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["run_code"],
        tool_policies={"run_code": "approval"},
    )
    model = scripted_model(
        turns=[
            ToolTurn((ToolCall("run_code", {"task": "Sum the data"}, "run-code-approval"),)),
            "The approved computation completed.",
        ]
    )

    suspended = await run_scenario(db_session_factory, context, model=model)

    assert suspended.run.status == RUN_STATUS_AWAITING_APPROVAL
    assert executed == []
    state = load_suspended_run_state(suspended.run)
    resumed = await run_scenario(
        db_session_factory,
        context,
        model=model,
        prompt=None,
        expected_status=RUN_STATUS_AWAITING_APPROVAL,
        message_history=state.message_history,
        deferred_tool_results=DeferredToolResults(
            approvals={state.pending_tool_call_ids[0]: ToolApproved()}
        ),
    )

    assert resumed.run.status == "completed"
    assert executed == ["Sum the data"]
    assert {row.details["outcome"] for row in resumed.audit_rows} == {
        "approval_requested",
        "completed",
    }


async def test_run_code_approval_evidence_names_every_outbound_file(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_openai(monkeypatch)
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["run_code"],
        tool_policies={"run_code": "approval"},
    )
    file_id = uuid4()
    suspended = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            "run_code",
                            {
                                "task": "Review the named workbook",
                                "file_ids": [_file_reference(file_id, "payroll.xlsx")],
                                "model_provider": "openai",
                            },
                            "named-file-approval",
                        ),
                    )
                )
            ]
        ),
    )

    assert suspended.run.status == RUN_STATUS_AWAITING_APPROVAL
    state = load_suspended_run_state(suspended.run)
    evidence = json.dumps(state.message_history, default=str)
    assert "payroll.xlsx" in evidence
    assert str(file_id) in evidence


async def test_run_code_declared_edit_appends_agent_revision(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    run_code_storage: None,
) -> None:
    _enable_openai(monkeypatch)
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["run_code"],
        tool_policies={"run_code": "auto"},
    )
    file_id, original_revision_id = await _create_source_file(
        db_session_factory,
        workspace_id=context.workspace_id,
        user_id=context.user_id,
    )

    async def fake_execution(*, deps, task, inputs, model_spec, edit_target, tool_call_id):
        del deps, inputs, tool_call_id
        assert task == "Add a totals row"
        assert model_spec.provider == "openai"
        assert edit_target is not None
        return (
            "Updated [budget](sandbox:/mnt/data/budget-with-totals.csv).",
            [
                run_code_tools.CapturedSandboxFile(
                    name="budget-with-totals.csv",
                    content=b"month,amount\nAugust,42\nTotal,42\n",
                    media_type="text/csv",
                )
            ],
            [],
        )

    monkeypatch.setattr(run_code_tools, "run_native_code_execution", fake_execution)
    reference = _file_reference(file_id)
    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            "run_code",
                            {
                                "task": "Add a totals row",
                                "file_ids": [reference],
                                "updates_file_id": reference,
                                "model_provider": "openai",
                            },
                            "edit-file",
                        ),
                    )
                ),
                "The workbook now includes a totals row.",
            ]
        ),
    )

    assert result.run.status == "completed"
    async with db_session_factory() as db:
        file = await db.get(File, file_id)
        assert file is not None
        assert file.revision_count == 2
        assert file.current_revision_id != original_revision_id
        revision = await db.get(FileRevision, file.current_revision_id)
        assert revision is not None
        assert revision.created_by_agent_id == context.agent_id
        assert revision.revision_kind == "edit"


async def test_run_code_conflict_preserves_the_first_concurrent_revision(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    run_code_storage: None,
) -> None:
    _enable_openai(monkeypatch)
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["run_code"],
        tool_policies={"run_code": "auto"},
    )
    file_id, _original_revision_id = await _create_source_file(
        db_session_factory,
        workspace_id=context.workspace_id,
        user_id=context.user_id,
    )

    async def fake_execution(*, deps, task, inputs, model_spec, edit_target, tool_call_id):
        del task, inputs, model_spec, tool_call_id
        assert edit_target is not None
        await append_file_revision(
            deps.db,
            workspace=deps.workspace,
            file_id=edit_target.file_id,
            content=b"month,amount\nAugust,43\n",
            actor=FileRevisionActor(user_id=deps.user.id),
            expected_current_revision_id=edit_target.revision_id,
        )
        return (
            "Updated the workbook.",
            [
                run_code_tools.CapturedSandboxFile(
                    name="budget-with-totals.csv",
                    content=b"month,amount\nAugust,42\nTotal,42\n",
                    media_type="text/csv",
                )
            ],
            [],
        )

    monkeypatch.setattr(run_code_tools, "run_native_code_execution", fake_execution)
    reference = _file_reference(file_id)
    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            "run_code",
                            {
                                "task": "Add a totals row",
                                "file_ids": [reference],
                                "updates_file_id": reference,
                                "model_provider": "openai",
                            },
                            "conflicting-edit",
                        ),
                    )
                ),
                "The file changed before the sandbox edit could be saved.",
            ]
        ),
    )

    assert result.run.status == "completed"
    assert result.output == "The file changed before the sandbox edit could be saved."
    async with db_session_factory() as db:
        file = await db.get(File, file_id)
        assert file is not None
        assert file.revision_count == 2
        current = await db.get(FileRevision, file.current_revision_id)
        assert current is not None
        assert current.created_by_user_id == context.user_id


@pytest.mark.parametrize(
    ("policy", "expected_status", "expected_tasks"),
    [
        ("auto", "completed", ["Build the scheduled digest"]),
        ("approval", RUN_STATUS_AWAITING_APPROVAL, []),
    ],
)
async def test_scheduled_run_code_respects_tool_policy_for_internal_execution(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    policy: str,
    expected_status: str,
    expected_tasks: list[str],
) -> None:
    _enable_openai(monkeypatch)
    executed: list[str] = []
    _script_run_code(monkeypatch, executed)
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["run_code"],
        tool_policies={"run_code": policy},
        trigger="scheduled",
        metadata={"envelope": {"side_effect_policy": "require_approval"}},
    )
    turns: list[ToolTurn | str] = [
        ToolTurn((ToolCall("run_code", {"task": "Build the scheduled digest"}),))
    ]
    if policy == "auto":
        turns.append("The scheduled digest is ready.")

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(turns=turns),
    )

    assert result.run.status == expected_status
    assert executed == expected_tasks
