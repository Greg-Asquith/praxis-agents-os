"""Tenant reads select published revisions and stop after withdrawal."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from core.database import maintenance_async_db_session, set_session_tenant_context
from core.exceptions.general import NotFoundError
from models.files import File, FileRevision
from services.files.create_file_download import create_file_download
from services.files.create_file_preview import create_file_preview
from services.files.domain import FileDownloadRequest
from services.files.get_file import get_file
from services.files.get_file_revision_content import get_file_revision_content
from services.files.list_file_revisions import list_file_revisions
from services.files.list_files import list_files
from services.files.platform.withdraw_file import withdraw_file
from services.storage.domain import StorageBucket
from tests.services.files.test_platform_file_management import (
    _draft,
    _publish,
    management_context as management_context,
)
from tests.support.requests import build_test_request


async def test_tenant_reads_keep_published_snapshot(
    db_session, db_session_factory, management_context
):
    actor = management_context["actor"]
    first = await _draft(db_session, management_context)
    await _publish(db_session, actor, first)
    replacement = await _draft(
        db_session, management_context, file_id=first.id, content=b"unpublished replacement"
    )
    workspace = management_context["workspace"]
    async with db_session_factory() as tenant:
        await set_session_tenant_context(tenant, workspace_id=workspace.id, user_id=actor.id)
        result = await get_file(tenant, workspace=workspace, file_id=first.id)
        assert result.current_revision_id == first.current_revision_id
        assert result.size_bytes == 5
        assert result.revision_count == 1
        assert result.processing_status == "ready"
        listed = await list_files(tenant, workspace=workspace, sort_by="size_bytes")
        assert listed.total == 1
        assert listed.files[0] == result
        history = await list_file_revisions(tenant, workspace=workspace, file_id=first.id)
        assert [revision.id for revision in history.revisions] == [first.current_revision_id]
        content = await get_file_revision_content(
            tenant,
            workspace=workspace,
            actor=actor,
            request=build_test_request(),
            file_id=first.id,
            revision_id=first.current_revision_id,
        )
        assert content.content == "hello"
        grant = await create_file_download(
            tenant,
            workspace=workspace,
            actor=actor,
            request=build_test_request(),
            file_id=first.id,
            payload=FileDownloadRequest(),
        )
        assert grant.download.ref.bucket == StorageBucket.PLATFORM_PRIVATE
        assert str(first.current_revision_id) in grant.download.ref.key
        for revision_id in (replacement.current_revision_id, uuid4()):
            with pytest.raises(NotFoundError):
                await get_file_revision_content(
                    tenant,
                    workspace=workspace,
                    actor=actor,
                    request=build_test_request(),
                    file_id=first.id,
                    revision_id=revision_id,
                )
    async with maintenance_async_db_session() as db:
        stored = await db.get(File, first.id)
        assert stored.current_revision_id == replacement.current_revision_id
        assert stored.size_bytes == len(b"unpublished replacement")


async def test_withdrawal_blocks_every_tenant_file_read(
    db_session, db_session_factory, management_context
):
    actor = management_context["actor"]
    file = await _draft(db_session, management_context, image=True)
    await _publish(db_session, actor, file)
    workspace = management_context["workspace"]
    async with db_session_factory() as tenant:
        await set_session_tenant_context(tenant, workspace_id=workspace.id, user_id=actor.id)
        preview = await create_file_preview(tenant, workspace=workspace, file_id=file.id)
        assert preview.preview.ref.bucket == StorageBucket.PLATFORM_PRIVATE
    await withdraw_file(db_session, actor=actor, request=build_test_request(), file_id=file.id)
    async with db_session_factory() as tenant:
        await set_session_tenant_context(tenant, workspace_id=workspace.id, user_id=actor.id)
        assert (await list_files(tenant, workspace=workspace)).total == 0
        for operation in (get_file, list_file_revisions, create_file_preview):
            with pytest.raises(NotFoundError):
                await operation(tenant, workspace=workspace, file_id=file.id)
        with pytest.raises(NotFoundError):
            await create_file_download(
                tenant,
                workspace=workspace,
                actor=actor,
                request=build_test_request(),
                file_id=file.id,
                payload=FileDownloadRequest(revision_id=file.current_revision_id),
            )
        with pytest.raises(NotFoundError):
            await get_file_revision_content(
                tenant,
                workspace=workspace,
                actor=actor,
                request=build_test_request(),
                file_id=file.id,
                revision_id=file.current_revision_id,
            )
        assert not list(
            await tenant.scalars(select(FileRevision).where(FileRevision.file_id == file.id))
        )
