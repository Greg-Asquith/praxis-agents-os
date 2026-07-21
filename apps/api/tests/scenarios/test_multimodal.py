# apps/api/tests/scenarios/test_multimodal.py

"""Multimodal attachment resolution through the real runtime turn."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from pydantic_ai.messages import BinaryContent, ModelRequest, UserPromptPart
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.settings import settings
from models.workspace import Workspace
from services.files.contract import contract_for_content_type
from services.files.utils import private_ref_from_key, revision_object_key, sha256_hex
from services.storage.factory import get_storage_provider
from tests.factories import build_file, build_file_revision
from tests.support.scenario import build_scenario_agent, run_scenario, scripted_model
from tests.support.storage import reset_storage_provider_cache


@pytest.fixture
def scenario_local_storage(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()
    try:
        yield
    finally:
        reset_storage_provider_cache()


async def test_attachment_id_resolves_to_binary_content(
    db_session_factory: async_sessionmaker[AsyncSession],
    scenario_local_storage: None,
) -> None:
    context = await build_scenario_agent(db_session_factory)
    content = b"png"
    async with db_session_factory() as db:
        workspace = await db.get(Workspace, context.workspace_id)
        assert workspace is not None
        contract = contract_for_content_type("image/png")
        file = build_file(
            workspace=workspace,
            name="screen.png",
            category=contract.category.value,
            content_type=contract.content_type,
            extension=contract.extensions[0],
            size_bytes=len(content),
            content_hash=sha256_hex(content),
        )
        db.add(file)
        await db.flush()
        revision_id = uuid4()
        object_key = revision_object_key(
            context.workspace_id, file.id, revision_id, contract.extensions[0]
        )
        await get_storage_provider().put_object(
            private_ref_from_key(object_key), content, content_type="image/png"
        )
        revision = build_file_revision(
            file,
            revision_id=revision_id,
            created_by_user_id=context.user_id,
            object_key=object_key,
            size_bytes=len(content),
            content_hash=sha256_hex(content),
        )
        db.add(revision)
        await db.flush()
        file.current_revision_id = revision.id
        file.revision_count = 1
        await db.commit()
        file_id = file.id

    seen = []
    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(turns=["I see the image."], seen_requests=seen),
        prompt="Describe this",
        attachment_file_ids=[file_id],
    )

    prompt = next(
        part.content
        for message in seen[0][0]
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart)
    )
    assert isinstance(prompt, list)
    attachment = prompt[1]
    assert isinstance(attachment, BinaryContent)
    assert attachment.data == content
    assert attachment.media_type == "image/png"
    assert attachment.identifier == str(file_id)
    assert result.run.status == "completed"
