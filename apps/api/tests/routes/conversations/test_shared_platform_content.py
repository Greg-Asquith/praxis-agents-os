# apps/api/tests/routes/conversations/test_shared_platform_content.py

"""Checks platform resource access from saved shared-chat references."""

from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from sqlalchemy import select

from core.database import maintenance_async_db_session, set_session_tenant_context
from models.files import FileReference
from models.workspace import WorkspaceRole
from services.agents.runtime.persistence import persist_new_messages
from services.artifacts.platform.delete_artifact import delete_artifact
from services.artifacts.platform.withdraw_artifact import withdraw_artifact
from services.files.create_conversation_file_references import create_conversation_file_references
from services.files.platform.delete_file import delete_file
from services.files.platform.withdraw_file import withdraw_file
from tests.security.test_conversation_sharing import set_sharing, sharing_case
from tests.services.files.test_platform_file_management import (
    _draft,
    _publish,
    management_context as management_context,
)
from tests.support.platform_artifacts import seed_published_artifact
from tests.support.requests import build_test_request


@pytest.mark.parametrize("lifecycle", ["withdraw", "delete"])
async def test_shared_platform_references_recheck_publication(
    db_session, db_async_client, management_context, lifecycle
):
    case = await sharing_case(db_session, role=WorkspaceRole.READ_ONLY)
    manager = management_context["actor"]
    file = await _draft(db_session, management_context, content=b"Reviewed template")
    await _publish(db_session, manager, file)
    async with maintenance_async_db_session() as db:
        artifact, version = await seed_published_artifact(db, workspace=case.workspace)

    await set_session_tenant_context(
        db_session, workspace_id=case.workspace.id, user_id=case.owner.id
    )
    await create_conversation_file_references(
        db_session,
        workspace_id=case.workspace.id,
        conversation_id=case.conversation.id,
        file_ids=[file.id],
        created_by_user_id=case.owner.id,
    )
    answer = f"[Template](/files?fileId={file.id}) and [Report](/artifacts/{artifact.id})"
    await persist_new_messages(
        db_session,
        conversation=case.conversation,
        run_id=uuid4(),
        messages=[ModelResponse(parts=[TextPart(answer)])],
    )
    await db_session.commit()
    assert (await set_sharing(db_async_client, case, "workspace")).status_code == 200
    transcript_path = f"/api/v1/conversations/{case.conversation.id}/messages"
    transcript = await db_async_client.get(transcript_path, headers=case.viewer_headers)
    assert transcript.status_code == 200
    assert transcript.json()["access"] == "viewer"
    assert answer in transcript.text

    download_path = f"/api/v1/files/{file.id}/download"
    pin = {"revision_id": str(file.current_revision_id)}
    download = await db_async_client.post(download_path, headers=case.viewer_headers, json=pin)
    assert download.status_code == 200, download.text
    parsed = urlsplit(download.json()["download"]["url"])
    content = await db_async_client.get(f"{parsed.path}?{parsed.query}")
    assert content.status_code == 200
    assert content.text == "Reviewed template"
    detail_path = f"/api/v1/artifacts/{artifact.id}"
    detail = await db_async_client.get(detail_path, headers=case.viewer_headers)
    assert detail.status_code == 200
    assert detail.json()["scope"] == "platform"
    assert detail.json()["can_edit"] is False
    view_path = f"{detail_path}/versions/{version.id}/view-url"
    view = await db_async_client.get(view_path, headers=case.viewer_headers)
    assert view.status_code == 200
    parsed_view = urlsplit(view.json()["url"])
    signed_view_path = f"{parsed_view.path}?{parsed_view.query}"
    assert (await db_async_client.get(signed_view_path)).text == "Published report"

    file_operation = withdraw_file if lifecycle == "withdraw" else delete_file
    await file_operation(db_session, actor=manager, request=build_test_request(), file_id=file.id)
    artifact_operation = withdraw_artifact if lifecycle == "withdraw" else delete_artifact
    await artifact_operation(
        db_session,
        actor=manager,
        workspace=management_context["workspace"],
        request=build_test_request(),
        artifact_id=artifact.id,
    )
    assert (
        await db_async_client.post(download_path, headers=case.viewer_headers, json=pin)
    ).status_code == 404
    for path in (detail_path, view_path, signed_view_path):
        response = await db_async_client.get(path, headers=case.viewer_headers)
        assert response.status_code == 404, response.text

    # Saved answers remain readable; destination APIs revoke fresh resource access.
    transcript = await db_async_client.get(transcript_path, headers=case.viewer_headers)
    assert transcript.status_code == 200
    assert answer in transcript.text
    await set_session_tenant_context(
        db_session, workspace_id=case.workspace.id, user_id=case.viewer.id
    )
    reference = await db_session.scalar(
        select(FileReference).where(FileReference.file_id == file.id)
    )
    assert reference.workspace_id == case.workspace.id
    assert reference.file_revision_id == file.current_revision_id
    assert reference.target_id == case.conversation.id
