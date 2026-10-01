"""Input gates for Files that document tools load, such as images added to a deck."""

from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import FileReference
from services.documents import inputs as document_inputs
from services.files.contract import FileCategory
from services.files.create_file_with_revision import create_file_with_revision
from services.files.revision_actor import FileRevisionActor
from tests.factories import build_user, build_workspace


@pytest.mark.asyncio
async def test_input_gates_reject_out_of_scope_and_oversized_files(
    db_session: AsyncSession,
    local_storage: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = build_user(email=f"input-gates-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"input-gates-{uuid4().hex[:8]}")
    other_workspace = build_workspace(slug=f"input-other-{uuid4().hex[:8]}")
    db_session.add_all([user, workspace, other_workspace])
    await db_session.flush()

    async def load(reference: FileReference, *, max_total_bytes: int = 64):
        ctx = RunContext(
            deps=cast(RuntimeDeps, SimpleNamespace(db=db_session, workspace=workspace)),
            model=TestModel(),
            usage=RunUsage(),
        )
        return await document_inputs.load_input_files(
            ctx,
            [reference],
            tool_name="edit_presentation",
            categories={FileCategory.IMAGE},
            max_file_bytes=64,
            max_total_bytes=max_total_bytes,
        )

    async def create(target_workspace, name: str, content: bytes, content_type: str):
        created = await create_file_with_revision(
            db_session,
            workspace=target_workspace,
            name=name,
            content=content,
            content_type=content_type,
            extension=Path(name).suffix,
            actor=FileRevisionActor(user_id=user.id),
        )
        return created.file, FileReference(entity_id=created.file.id, label=name)

    _, foreign = await create(other_workspace, "foreign.png", b"\x89PNG", "image/png")
    with pytest.raises(ModelRetry, match="File not found"):
        await load(foreign)

    _, text = await create(workspace, "data.csv", b"a,b\n1,2\n", "text/csv")
    with pytest.raises(ModelRetry, match="file type that edit_presentation can't use"):
        await load(text)

    image_file, image = await create(workspace, "chart.png", b"\x89PNG\r\n\x1a\n", "image/png")
    with pytest.raises(ModelRetry, match="too large together"):
        await load(image, max_total_bytes=4)

    class FakeStorage:
        payload = b"x" * 65

        async def get_object(self, ref) -> bytes:
            del ref
            return self.payload

    monkeypatch.setattr(document_inputs, "get_storage_provider", lambda: FakeStorage())
    with pytest.raises(ModelRetry, match="larger than edit_presentation allows"):
        await load(image)

    image_file.deleted = True
    await db_session.flush()
    with pytest.raises(ModelRetry, match="File not found"):
        await load(image)
