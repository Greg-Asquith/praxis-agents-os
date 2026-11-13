# apps/api/tests/scenarios/test_google_ads_upload_media_review.py

"""Files added on the Google Ads upload card are checked and pinned before approval."""

from collections.abc import Iterator
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from sqlalchemy import select

from core.settings import settings
from integrations.google_ads.tools.upload_media import DEFINITION
from models.agent_run import AgentRun
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agent_runs.review_approval import review_agent_run_approval
from services.agent_runs.schemas import AgentRunReviewApprovalRequest
from services.agents.runtime.approval_projection import build_approval_graph, project_approval_graph
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.files.contract import FileCategory
from services.files.utils import private_ref_from_key
from services.integrations.context.domain import ResolvedActiveContext
from services.storage.factory import get_storage_provider
from tests.factories import build_file, build_file_revision
from tests.integrations.google_ads.test_upload_media_tool import _ENTRY
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)
from tests.support.storage import reset_storage_provider_cache


@pytest.fixture
def local_storage(tmp_path, monkeypatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()
    try:
        yield
    finally:
        reset_storage_provider_cache()


async def _file(session_factory, context, *, name, category, content_type, extension, content):
    async with session_factory() as db:
        workspace = await db.get_one(Workspace, context.workspace_id)
        digest = sha256(content).hexdigest()
        file = build_file(
            workspace=workspace,
            name=name,
            category=category.value,
            content_type=content_type,
            extension=extension,
            size_bytes=len(content),
            content_hash=digest,
        )
        db.add(file)
        await db.flush()
        revision = build_file_revision(
            file, created_by_user_id=context.user_id, size_bytes=len(content), content_hash=digest
        )
        await get_storage_provider().put_object(
            private_ref_from_key(revision.object_key), content, content_type=content_type
        )
        db.add(revision)
        await db.flush()
        file.current_revision_id = revision.id
        file.revision_count = 1
        await db.commit()
        return {"entity_kind": "file", "entity_id": str(file.id), "label": name}


async def test_files_added_to_a_link_only_request_are_checked_and_pinned(
    db_session_factory, monkeypatch, local_storage
):
    monkeypatch.setitem(
        RUNTIME_TOOL_CATALOG, DEFINITION.name, replace(DEFINITION, availability_check=lambda: True)
    )
    active = AsyncMock(return_value=ResolvedActiveContext(entries=(_ENTRY,)))
    monkeypatch.setattr("services.agents.runtime.execute.setup.resolve_active_context", active)
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.resolve_active_context", active
    )
    context = await build_scenario_agent(db_session_factory, tool_names=[DEFINITION.name])
    video = await _file(
        db_session_factory,
        context,
        name="trail-fit-launch.mp4",
        category=FileCategory.VIDEO,
        content_type="video/mp4",
        extension=".mp4",
        content=b"VIDEOBYTES",
    )
    buffer = BytesIO()
    Image.new("RGB", (400, 400), "white").save(buffer, "PNG")
    image = await _file(
        db_session_factory,
        context,
        name="logo-mark.png",
        category=FileCategory.IMAGE,
        content_type="image/png",
        extension=".png",
        content=buffer.getvalue(),
    )
    details = [{"file_id": video["entity_id"], "title": "Trail Fit Launch"}]
    # The agent only linked a video, so the Files and the title are all added on the card.
    proposed = {"youtube_videos": ["https://youtu.be/dQw4w9WgXcQ"]}
    model = scripted_model(
        turns=[ToolTurn((ToolCall(DEFINITION.name, proposed, "upload"),)), "Done."]
    )
    suspended = await run_scenario(db_session_factory, context, model=model)
    assert suspended.run.status == "awaiting_approval"

    async with db_session_factory() as db:
        root = await db.get(AgentRun, context.run_id)
        projection = project_approval_graph(build_approval_graph(root, {root.id: root}))
        membership = await db.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == context.workspace_id,
                WorkspaceMembership.user_id == context.user_id,
            )
        )
        await review_agent_run_approval(
            db,
            actor=await db.get(User, context.user_id),
            workspace=await db.get(Workspace, context.workspace_id),
            membership=membership,
            run_id=root.id,
            payload=AgentRunReviewApprovalRequest(
                approval_id=projection.approvals[0].approval_id,
                approval_revision=projection.approval_revision,
                override_args={**proposed, "files": [video, image], "video_details": details},
            ),
        )
    async with db_session_factory() as db:
        state = load_suspended_run_state(await db.get(AgentRun, context.run_id))
    shown = state.deferred_tool_requests.metadata["upload"]["display_args"]["_files"]
    assert [(item["kind"], item["problem"]) for item in shown] == [("video", None), ("image", None)]
