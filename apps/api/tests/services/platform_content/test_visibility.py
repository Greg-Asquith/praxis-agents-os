"""Executes visibility predicates without relying on RLS to hide mistakes."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

# ruff: noqa: S608
from sqlalchemy import Boolean, bindparam, select, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from core.database import maintenance_async_db_session
from models.artifacts import Artifact, ArtifactRevision
from models.files import File, FileRevision
from models.kb import KBChunk, KBDocument
from services.artifacts.visibility import visible_artifact_filter, visible_artifact_revision_filter
from services.files.visibility import visible_file_filter, visible_file_revision_filter
from services.kb.visibility import VISIBLE_CHUNK_SQL, visible_chunk_filter, visible_document_filter
from tests.factories import (
    build_artifact,
    build_artifact_revision,
    build_file,
    build_file_revision,
    build_kb_chunk,
    build_kb_document,
    build_user,
    build_workspace,
)


async def _resource(db, kind, workspace, *, platform=False, published=False, deleted=False):
    if kind == "file":
        parent = build_file(workspace=workspace)
        child = build_file_revision(parent)
        pointer, published_pointer = "current_revision_id", "published_revision_id"
    elif kind == "artifact":
        parent = build_artifact(workspace=workspace)
        child = build_artifact_revision(artifact=parent)
        pointer, published_pointer = "current_version_id", "published_version_id"
    else:
        parent = build_kb_document(workspace=workspace, is_private=False)
        child = build_kb_chunk(document=parent)
        pointer = published_pointer = None
    child.scope = parent.scope = "platform" if platform else "workspace"
    if platform:
        parent.workspace_id = child.workspace_id = None
    if kind != "kb":
        child.object_key = f"platform/test/{child.id}.txt" if platform else child.object_key
    db.add(parent)
    await db.flush()
    db.add(child)
    await db.flush()
    if pointer:
        setattr(parent, pointer, child.id)
    if published:
        child.is_published = True
        await db.flush()
        if published_pointer:
            setattr(parent, published_pointer, child.id)
        parent.is_published = True
    if deleted:
        parent.soft_delete(cascade=False)
    await db.flush()
    return parent, child


@pytest.mark.parametrize("kind", ["file", "artifact", "kb"])
async def test_parent_and_child_visibility_matrix(db_session_factory, kind):
    models = {
        "file": (File, FileRevision),
        "artifact": (Artifact, ArtifactRevision),
        "kb": (KBDocument, KBChunk),
    }
    parent_model, child_model = models[kind]
    async with maintenance_async_db_session() as db:
        a, b = build_workspace(slug="a"), build_workspace(slug="b")
        db.add_all([a, b])
        await db.flush()
        local_a = await _resource(db, kind, a)
        local_b = await _resource(db, kind, b)
        published = await _resource(db, kind, a, platform=True, published=True)
        await _resource(db, kind, a, platform=True)
        withdrawn, _ = await _resource(db, kind, a, platform=True, published=True)
        withdrawn.is_published = False
        await _resource(db, kind, a, platform=True, published=True, deleted=True)
        await _resource(db, kind, a, deleted=True)
        await db.flush()

        # A draft revision under a published parent must not become readable.
        if kind != "kb":
            parent, _ = published
            if kind == "file":
                draft = FileRevision(file_id=parent.id, content_type="text/plain", extension=".txt")
            else:
                draft = ArtifactRevision(
                    artifact_id=parent.id, content_type="text/plain", extension=".txt"
                )
            draft.id = uuid4()
            draft.scope = "platform"
            draft.workspace_id = None
            draft.revision_number = 2
            draft.revision_kind = "edit"
            draft.size_bytes = 1
            draft.content_hash = "b" * 64
            draft.object_key = f"platform/test/{draft.id}.txt"
            draft.created_by_system = True
            db.add(draft)
            await db.flush()

        for workspace, local in [(a, local_a), (b, local_b), (None, None)]:
            workspace_id = workspace.id if workspace else None
            if kind == "file":
                parent_filter = visible_file_filter(workspace_id)
                child_filter = visible_file_revision_filter(workspace_id)
            elif kind == "artifact":
                parent_filter = visible_artifact_filter(workspace_id)
                child_filter = visible_artifact_revision_filter(workspace_id)
            else:
                parent_filter = visible_document_filter(workspace_id, None)
                child_filter = visible_chunk_filter(workspace_id, None)
            parent_ids = set(await db.scalars(select(parent_model.id).where(parent_filter)))
            child_ids = set(await db.scalars(select(child_model.id).where(child_filter)))
            assert parent_ids == ({local[0].id, published[0].id} if local else set())
            assert child_ids == ({local[1].id, published[1].id} if local else set())


@pytest.mark.parametrize("private_only", [False, True])
@pytest.mark.parametrize("user_present", [False, True])
async def test_kb_sql_matches_orm_privacy_source_access_and_scope(
    db_session_factory, private_only, user_present
):
    async with maintenance_async_db_session() as db:
        workspace, other_workspace = build_workspace(slug="a"), build_workspace(slug="b")
        user, other_user = build_user(email="a@example.com"), build_user(email="b@example.com")
        db.add_all([workspace, other_workspace, user, other_user])
        await db.flush()
        local = await _resource(db, "kb", workspace)
        own_private = await _resource(db, "kb", workspace)
        own_private[0].is_private = True
        own_private[0].created_by_user_id = user.id
        other_private = await _resource(db, "kb", workspace)
        other_private[0].is_private = True
        other_private[0].created_by_user_id = other_user.id
        ownerless_private = await _resource(db, "kb", workspace)
        ownerless_private[0].is_private = True
        await _resource(db, "kb", other_workspace)
        platform = await _resource(db, "kb", workspace, platform=True, published=True)
        await _resource(db, "kb", workspace, platform=True)
        withdrawn = await _resource(db, "kb", workspace, platform=True, published=True)
        withdrawn[0].is_published = False
        await _resource(db, "kb", workspace, platform=True, published=True, deleted=True)
        legacy_deleted = await _resource(db, "kb", workspace)
        legacy_deleted[0].deleted_at = datetime.now(UTC)
        ready = []
        for source in ["url", "integration"]:
            for status in ["ready", "pending", "error", "unavailable", "disconnected"]:
                parent, chunk = await _resource(db, "kb", workspace)
                parent.source_type = source
                parent.external_id = str(uuid4()) if source == "integration" else None
                parent.source_sync_status = status
                if status == "ready":
                    ready.append(chunk.id)
        await db.flush()
        user_id = user.id if user_present else None
        expected = {own_private[1].id} if user_present else set()
        if not private_only:
            expected |= {local[1].id, platform[1].id, *ready}
        statement = text(
            "SELECT c.id FROM kb_chunks c JOIN kb_documents d ON d.id = c.document_id WHERE "
            + VISIBLE_CHUNK_SQL
        ).bindparams(
            bindparam("workspace_id", type_=PGUUID(as_uuid=True)),
            bindparam("user_id", type_=PGUUID(as_uuid=True)),
            bindparam("private_only", type_=Boolean()),
        )
        for workspace_id in [workspace.id, None]:
            orm_ids = set(
                await db.scalars(
                    select(KBChunk.id).where(
                        visible_chunk_filter(workspace_id, user_id, private_only=private_only)
                    )
                )
            )
            sql_ids = set(
                await db.scalars(
                    statement,
                    {
                        "workspace_id": workspace_id,
                        "user_id": user_id,
                        "private_only": private_only,
                    },
                )
            )
            assert orm_ids == sql_ids == (expected if workspace_id else set())
