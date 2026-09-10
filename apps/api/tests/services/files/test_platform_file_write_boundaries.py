"""Workspace mutations reject published platform targets without changing them."""

import importlib
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry
from sqlalchemy import func, select

from core.database import maintenance_async_db_session, set_session_tenant_context
from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError, NotFoundError
from models.audit_event import AuditEvent
from models.files import File, FileRevision, FileUpload
from models.workspace import WorkspaceRole
from services.agents.runtime.entity_references.domain import FileReference
from services.agents.runtime.tools.files.write_file import write_file
from services.files.domain import (
    FileEditRequest,
    FileMoveRequest,
    FileRestoreRequest,
    FileUpdateRequest,
    FileUploadRequest,
)
from services.files.revision_actor import FileRevisionActor
from tests.factories import build_file, build_user, build_workspace, build_workspace_membership
from tests.support.requests import build_test_request
from utils.content import ContentScope


@pytest.fixture
async def write_context(db_session_factory):
    async with maintenance_async_db_session() as db:
        actor, workspace = build_user(), build_workspace()
        membership = build_workspace_membership(
            workspace_id=workspace.id, user_id=actor.id, role=WorkspaceRole.OWNER
        )
        db.add_all([actor, workspace, membership])
        await db.flush()
        file = build_file(
            workspace=workspace,
            scope=ContentScope.PLATFORM,
            workspace_id=None,
            name="policy.txt",
            extension=".txt",
            category="editable_text",
            content_type="text/plain",
        )
        local = build_file(workspace=workspace)
        db.add_all([file, local])
        await db.flush()
        revision = FileRevision(
            id=uuid4(),
            file_id=file.id,
            scope=ContentScope.PLATFORM,
            workspace_id=None,
            revision_number=1,
            revision_kind="create",
            content_type=file.content_type,
            extension=file.extension,
            size_bytes=file.size_bytes,
            content_hash=file.content_hash,
            object_key=f"platform/files/{file.id}/{uuid4()}.txt",
            created_by_user_id=actor.id,
            is_published=True,
        )
        db.add(revision)
        await db.flush()
        file.current_revision_id = revision.id
        file.published_revision_id = revision.id
        file.revision_count = 1
        file.is_published = True
    return actor, workspace, membership, file, local


async def _mutate(operation, db, context):
    actor, workspace, membership, file, local = context
    common = {
        "actor": actor,
        "workspace": workspace,
        "membership": membership,
        "request": build_test_request(),
    }
    kwargs = dict(common, file_id=file.id)
    if operation == "edit_file":
        kwargs["payload"] = FileEditRequest(
            content="changed", expected_current_revision_id=file.current_revision_id
        )
    elif operation == "update_file":
        kwargs["payload"] = FileUpdateRequest(name="renamed.txt", folder_id=None)
    elif operation == "restore_file_revision":
        kwargs["payload"] = FileRestoreRequest(
            revision_id=uuid4(), expected_current_revision_id=file.current_revision_id
        )
    elif operation == "create_file_upload":
        kwargs = {
            "actor": actor,
            "workspace": workspace,
            "membership": membership,
            "payload": FileUploadRequest(
                filename="policy.txt", content_type="text/plain", size_bytes=7, file_id=file.id
            ),
        }
    elif operation in {"move_files", "bulk_move"}:
        kwargs = dict(
            common,
            payload=FileMoveRequest(
                file_ids=[local.id, file.id] if operation == "bulk_move" else [file.id],
                folder_id=None,
            ),
        )
        operation = "move_files"
    elif operation == "append_file_revision":
        kwargs = {
            "workspace": workspace,
            "file_id": file.id,
            "content": b"changed",
            "actor": FileRevisionActor(user_id=actor.id),
        }
    elif operation == "write_agent_file":
        kwargs = {
            "workspace": workspace,
            "agent": SimpleNamespace(id=uuid4()),
            "name": "policy.txt",
            "content": "changed",
            "file_id": file.id,
            "expected_current_revision_id": file.current_revision_id,
        }
    module = importlib.import_module(f"services.files.{operation}")
    await getattr(module, operation)(db, **kwargs)


@pytest.mark.parametrize("published", [True, False])
@pytest.mark.parametrize(
    "operation",
    [
        "edit_file",
        "update_file",
        "restore_file_revision",
        "delete_file",
        "purge_file",
        "create_file_upload",
        "append_file_revision",
        "write_agent_file",
        "move_files",
        "bulk_move",
    ],
)
async def test_platform_file_workspace_mutations_preserve_visibility_and_state(
    db_session, write_context, operation, published
):
    actor, workspace, _, file, local = write_context
    if not published:
        async with maintenance_async_db_session() as db:
            stored = await db.get(File, file.id)
            stored.is_published = False
    await set_session_tenant_context(db_session, workspace_id=workspace.id, user_id=actor.id)
    expected = AuthorizationError if published else (NotFoundError, AppValidationError)
    with pytest.raises(expected) as failure:
        await _mutate(operation, db_session, write_context)
    if published:
        assert "workspace copy" in str(failure.value)
    else:
        assert "platform" not in str(failure.value).lower()
    await db_session.commit()
    async with maintenance_async_db_session() as db:
        stored = await db.get(File, file.id)
        assert stored.name == "policy.txt"
        assert not stored.deleted
        assert stored.folder_id is None
        assert stored.revision_count == 1
        assert stored.current_revision_id == file.current_revision_id
        assert (await db.get(File, local.id)).folder_id is None
        assert (
            await db.scalar(
                select(func.count()).select_from(FileUpload).where(FileUpload.file_id == file.id)
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.resource_id.in_([str(file.id), str(local.id)]))
            )
            == 0
        )


async def test_platform_file_approved_runtime_write_returns_workspace_copy_error(
    db_session, write_context
):
    actor, workspace, _, file, _ = write_context
    await set_session_tenant_context(db_session, workspace_id=workspace.id, user_id=actor.id)
    ctx = SimpleNamespace(
        tool_call_approved=True,
        deps=SimpleNamespace(db=db_session, workspace=workspace, agent=SimpleNamespace(id=uuid4())),
    )
    with pytest.raises(ModelRetry, match="workspace copy"):
        await write_file(
            ctx,
            name=file.name,
            content="changed",
            file_id=FileReference(entity_id=file.id, label=file.name),
            expected_current_revision_id=file.current_revision_id,
        )
    await db_session.commit()
    async with maintenance_async_db_session() as db:
        assert (await db.get(File, file.id)).revision_count == 1


async def test_platform_file_code_output_cannot_append_platform_revision(db_session, write_context):
    from pydantic_ai import ToolFailed

    from services.agents.runtime.tools.native.run_code_file_bridge import RunCodeEditTarget
    from services.agents.runtime.tools.native.run_code_outputs import (
        CapturedSandboxFile,
        persist_sandbox_outputs,
    )

    actor, workspace, _, file, _ = write_context
    await set_session_tenant_context(db_session, workspace_id=workspace.id, user_id=actor.id)
    deps = SimpleNamespace(db=db_session, workspace=workspace, agent=SimpleNamespace(id=uuid4()))
    with pytest.raises(ToolFailed, match="workspace copy"):
        await persist_sandbox_outputs(
            deps,
            task="Edit policy",
            captured=[
                CapturedSandboxFile(name=file.name, content=b"changed", media_type="text/plain")
            ],
            input_file_ids=[file.id],
            input_revision_ids=[file.current_revision_id],
            edit_target=RunCodeEditTarget(
                file_id=file.id,
                revision_id=file.current_revision_id,
                name=file.name,
                sandbox_name=file.name,
                media_type="text/plain",
            ),
        )
    await db_session.commit()
    async with maintenance_async_db_session() as db:
        assert (await db.get(File, file.id)).revision_count == 1
