# apps/api/tests/routes/web/test_save_fetched_page.py

"""A person saves a fetched page into Files from a fetch_url card."""

from sqlalchemy import select

from core.database import set_session_tenant_context
from models.audit_event import AuditEvent
from models.files import File, FileReference
from models.workspace import WorkspaceRole
from tests.factories.conversations import build_conversation
from tests.routes.integrations.conftest import create_identity
from tests.support.web import fake_web, html_page

_URL = "/api/v1/web/page-saves"


def _serve(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.web.save_fetched_page.fetch_url",
        fake_web({"shop.example/pricing": html_page("<h1>Pricing</h1>")}),
    )


async def test_save_fetched_page_saves_as_the_person_in_their_conversation(
    db_session, db_async_client, local_storage, monkeypatch
):
    _serve(monkeypatch)
    user, workspace, _membership, headers = await create_identity(
        db_session, role=WorkspaceRole.MEMBER
    )
    conversation = build_conversation(user=user, workspace=workspace)
    db_session.add(conversation)
    await db_session.commit()

    response = await db_async_client.post(
        _URL,
        json={"conversation_id": str(conversation.id), "url": "https://shop.example/pricing"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "shop.example - pricing.html" and body["content_type"] == "text/html"
    await set_session_tenant_context(db_session, workspace_id=workspace.id, user_id=user.id)
    file = await db_session.get(File, body["file_id"])
    assert file.workspace_id == workspace.id
    link = await db_session.scalar(select(FileReference).where(FileReference.file_id == file.id))
    assert link.target_id == conversation.id
    audit = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.resource_id == str(file.id))
    )
    assert audit.actor_id == str(user.id) and audit.details["url"] == "https://shop.example/pricing"


async def test_save_fetched_page_refuses_another_members_conversation(
    db_session, db_async_client, local_storage, monkeypatch
):
    _serve(monkeypatch)
    owner, workspace, _membership, _headers = await create_identity(
        db_session, role=WorkspaceRole.MEMBER
    )
    _other, _workspace, _other_membership, other_headers = await create_identity(
        db_session, role=WorkspaceRole.MEMBER, workspace=workspace
    )
    conversation = build_conversation(user=owner, workspace=workspace)
    db_session.add(conversation)
    await db_session.commit()

    response = await db_async_client.post(
        _URL,
        json={"conversation_id": str(conversation.id), "url": "https://shop.example/pricing"},
        headers=other_headers,
    )

    assert response.status_code == 404, response.text
    assert await db_session.scalar(select(File.id)) is None
