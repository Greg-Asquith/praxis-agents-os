"""Database-backed defaults, listing, and authority for workspace chat sharing."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from core.database import set_session_tenant_context
from models.audit_event import AuditEvent
from models.conversation import Conversation
from models.workspace import WorkspaceRole
from services.conversations.utils import default_conversation_visibility
from tests.factories import build_workspace, build_workspace_membership
from tests.security.test_conversation_sharing import set_sharing, sharing_case

FIELD = "conversations_shared_by_default"
MANAGERS = (WorkspaceRole.OWNER, WorkspaceRole.ADMIN)


@pytest.mark.parametrize("role", list(WorkspaceRole))
async def test_only_managers_change_default_sharing(db_session, db_async_client, role):
    case = await sharing_case(db_session, role=role)
    path = f"/api/v1/workspaces/{case.workspace.id}"
    detail = await db_async_client.get(path, headers=case.viewer_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()[FIELD] is False
    response = await db_async_client.patch(path, headers=case.viewer_headers, json={FIELD: True})
    assert response.status_code == (200 if role in MANAGERS else 403), response.text
    await db_session.refresh(case.workspace)
    assert case.workspace.conversations_shared_by_default is (role in MANAGERS)
    if role in MANAGERS:
        assert response.json()[FIELD] is True
    else:
        assert not list(
            await db_session.scalars(
                select(AuditEvent).where(AuditEvent.resource_id == str(case.workspace.id))
            )
        )


@pytest.mark.parametrize("actor", ["outsider", "former", "anonymous"])
async def test_default_sharing_preserves_workspace_update_denials(
    db_session, db_async_client, actor
):
    case = await sharing_case(db_session, role=WorkspaceRole.ADMIN)
    headers = case.viewer_headers
    if actor == "outsider":
        await db_session.delete(case.membership)
    elif actor == "former":
        case.membership.deleted = True
    else:
        headers = {}
    await db_session.commit()
    path = f"/api/v1/workspaces/{case.workspace.id}"
    ordinary = await db_async_client.patch(path, headers=headers, json={"name": "Denied"})
    response = await db_async_client.patch(path, headers=headers, json={FIELD: True})
    assert response.status_code == ordinary.status_code
    assert response.status_code in (401, 403, 404), response.text
    await db_session.refresh(case.workspace)
    assert case.workspace.conversations_shared_by_default is False


@pytest.mark.parametrize("personal,value", [(False, None), (True, True), (True, False)])
async def test_default_sharing_rejects_null_and_personal_workspace_fields(
    db_session, db_async_client, personal, value
):
    case = await sharing_case(db_session, role=WorkspaceRole.OWNER, personal=personal)
    response = await db_async_client.patch(
        f"/api/v1/workspaces/{case.workspace.id}",
        headers=case.owner_headers,
        json={FIELD: value},
    )
    assert response.status_code == 400, response.text
    assert response.json()["field"] == FIELD
    await db_session.refresh(case.workspace)
    assert case.workspace.conversations_shared_by_default is False


async def test_default_changes_audit_transitions_without_rewriting_chats(
    db_session, db_async_client
):
    case = await sharing_case(db_session, role=WorkspaceRole.OWNER)
    shared = Conversation(
        user_id=case.owner.id,
        created_by=case.owner.id,
        workspace_id=case.workspace.id,
        visibility="workspace",
        shared_at=datetime.now(UTC),
        shared_by_user_id=case.owner.id,
        title="Already shared",
    )
    db_session.add(shared)
    await db_session.commit()
    statement = (
        select(Conversation.__table__)
        .where(Conversation.workspace_id == case.workspace.id)
        .order_by(Conversation.id)
    )
    before = (await db_session.execute(statement)).mappings().all()
    path = f"/api/v1/workspaces/{case.workspace.id}"
    for value in (True, False):
        response = await db_async_client.patch(
            path, headers=case.owner_headers, json={FIELD: value}
        )
        assert response.status_code == 200, response.text
        assert response.json()[FIELD] is value
        assert (await db_session.execute(statement)).mappings().all() == before
    events = list(
        await db_session.scalars(
            select(AuditEvent).where(AuditEvent.resource_id == str(case.workspace.id))
        )
    )
    assert len(events) == 2
    assert {
        (event.details[FIELD]["previous"], event.details[FIELD]["value"]) for event in events
    } == {(False, True), (True, False)}
    for event in events:
        assert event.details["fields"] == [FIELD]
        assert event.action == "update"
        assert event.resource_type == "workspace"
        assert event.actor_user_id == case.owner.id
        assert event.workspace_id == case.workspace.id


@pytest.mark.parametrize("enabled", [False, True])
async def test_combined_listing_projects_and_paginates_only_visible_root_chats(
    db_session, db_async_client, enabled
):
    case = await sharing_case(db_session)
    case.workspace.conversations_shared_by_default = enabled
    case.conversation.visibility = "workspace"
    start = datetime(2026, 1, 1, tzinfo=UTC)
    case.conversation.last_message_at = start + timedelta(days=2)
    rows = [
        Conversation(
            user_id=case.viewer.id if own else case.owner.id,
            created_by=case.viewer.id if own else case.owner.id,
            workspace_id=case.workspace.id,
            title=f"Listed chat {index}",
            visibility=visibility,
            source=source,
            deleted=deleted,
            last_message_at=start + timedelta(days=index),
            unread=True,
            metadata_json={"secret": "OWNER_ONLY_METADATA"},
        )
        for index, (own, visibility, source, deleted) in enumerate(
            [
                (True, "private", "direct", False),
                (True, "workspace", "scheduled", False),
                (False, "private", "direct", False),
                (True, "workspace", "direct", True),
                (True, "private", "delegated", False),
                (False, "workspace", "direct", True),
                (False, "private", "delegated", False),
            ]
        )
    ]
    db_session.add_all(rows)
    await db_session.commit()
    other = build_workspace(slug=f"combined-other-{uuid4().hex}")
    db_session.add_all(
        [
            other,
            build_workspace_membership(workspace_id=other.id, user_id=case.viewer.id),
        ]
    )
    await db_session.commit()
    await set_session_tenant_context(db_session, workspace_id=other.id)
    db_session.add(
        Conversation(
            user_id=case.viewer.id,
            created_by=case.viewer.id,
            workspace_id=other.id,
            visibility="workspace",
            title="Other workspace",
            last_message_at=start + timedelta(days=10),
        )
    )
    await db_session.commit()
    await set_session_tenant_context(db_session, workspace_id=case.workspace.id)
    actual = []
    for offset in range(4):
        response = await db_async_client.get(
            "/api/v1/conversations/",
            headers=case.viewer_headers,
            params={"scope": "all", "limit": 1, "offset": offset},
        )
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 3
        actual.extend(response.json()["conversations"])
    assert [row["id"] for row in actual] == [
        str(case.conversation.id),
        str(rows[1].id),
        str(rows[0].id),
    ]
    assert actual[0]["access"] == "viewer"
    assert actual[0]["owner_name"] == case.owner.display_name
    assert not {"metadata", "unread", "active_run_id", "needs_approval"} & actual[0].keys()
    for row in actual[1:]:
        assert row["access"] == "owner"
        assert row["unread"] is True
        assert row["metadata"] == {"secret": "OWNER_ONLY_METADATA"}
        assert row["capabilities"]["can_reply"] is True


@pytest.mark.parametrize("actor", ["outsider", "former", "anonymous"])
async def test_combined_scope_preserves_membership_denials(db_session, db_async_client, actor):
    case = await sharing_case(db_session)
    case.workspace.conversations_shared_by_default = True
    case.conversation.visibility = "workspace"
    headers = case.viewer_headers
    if actor == "outsider":
        await db_session.delete(case.membership)
    elif actor == "former":
        case.membership.deleted = True
    else:
        headers = {}
    await db_session.commit()
    for scope in ("mine", "workspace_shared", "all"):
        response = await db_async_client.get(
            "/api/v1/conversations/", headers=headers, params={"scope": scope}
        )
        assert response.status_code in (401, 403, 404), response.text


async def test_personal_combined_scope_keeps_owner_only_rows(db_session, db_async_client):
    case = await sharing_case(db_session, personal=True)
    case.conversation.visibility = "workspace"
    await db_session.commit()
    for headers, expected in (
        (case.owner_headers, [str(case.conversation.id)]),
        (case.viewer_headers, []),
    ):
        for scope in ("mine", "all"):
            response = await db_async_client.get(
                "/api/v1/conversations/", headers=headers, params={"scope": scope}
            )
            assert response.status_code == 200, response.text
            assert [row["id"] for row in response.json()["conversations"]] == expected
            assert all(row["access"] == "owner" for row in response.json()["conversations"])


@pytest.mark.parametrize("role", list(WorkspaceRole))
async def test_default_shared_viewer_capabilities_and_revocation(db_session, db_async_client, role):
    case = await sharing_case(db_session, role=role)
    case.workspace.conversations_shared_by_default = True
    for field, value in default_conversation_visibility(
        case.workspace, shared_by_user_id=case.owner.id
    ).items():
        setattr(case.conversation, field, value)
    await db_session.commit()
    listing = await db_async_client.get(
        "/api/v1/conversations/?scope=all", headers=case.viewer_headers
    )
    assert listing.status_code == 200, listing.text
    detail = await db_async_client.get(
        f"/api/v1/conversations/{case.conversation.id}", headers=case.viewer_headers
    )
    assert detail.status_code == 200, detail.text
    for row in (listing.json()["conversations"][0], detail.json()):
        assert row["access"] == "viewer"
        assert row["capabilities"] == {
            "can_reply": False,
            "can_manage_sharing": False,
            "can_stop_sharing": role in MANAGERS,
        }
        assert not {"metadata", "unread", "active_run_id", "needs_approval"} & row.keys()
    revoked = await set_sharing(db_async_client, case, "private", viewer=role in MANAGERS)
    assert revoked.status_code == 200, revoked.text
    after = await db_async_client.get(
        "/api/v1/conversations/?scope=all", headers=case.viewer_headers
    )
    assert after.status_code == 200, after.text
    assert after.json()["total"] == 0
    assert after.json()["conversations"] == []
    detail = await db_async_client.get(
        f"/api/v1/conversations/{case.conversation.id}", headers=case.viewer_headers
    )
    assert detail.status_code == 404
