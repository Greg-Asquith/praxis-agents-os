"""Database-backed audience and ownership boundaries for shared conversations."""

from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlalchemy import select

from core.auth.sessions import session_manager
from models.audit_event import AuditEvent
from models.conversation import Conversation, ConversationMessage
from models.user import User
from models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers

pytestmark = pytest.mark.asyncio


@dataclass
class SharingCase:
    conversation: Conversation
    owner_headers: dict[str, str]
    viewer_headers: dict[str, str]
    owner_token: str
    membership: WorkspaceMembership
    workspace: Workspace
    owner: User
    viewer: User


async def sharing_case(db, *, role=WorkspaceRole.MEMBER, personal=False, source="direct"):
    owner = build_user(email=f"sharing-owner-{uuid4().hex}@example.com")
    viewer = build_user(email=f"sharing-viewer-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"sharing-{uuid4().hex}", is_personal=personal)
    membership = build_workspace_membership(workspace_id=workspace.id, user_id=viewer.id, role=role)
    conversation = Conversation(
        user_id=owner.id,
        created_by=owner.id,
        workspace_id=workspace.id,
        source=source,
        title="Shared answer",
        unread=True,
        metadata_json={"secret": "PRIVATE_CONVERSATION_METADATA"},
    )
    db.add_all(
        [
            owner,
            viewer,
            workspace,
            membership,
            build_workspace_membership(workspace_id=workspace.id, user_id=owner.id, role=role),
            conversation,
        ]
    )
    await db.flush()
    owner.default_workspace_id = workspace.id
    viewer.default_workspace_id = workspace.id
    for sequence in range(1, 6):
        db.add(
            ConversationMessage(
                conversation_id=conversation.id,
                workspace_id=workspace.id,
                role="user",
                sequence=sequence,
                parts={"parts": [{"part_kind": "user-prompt", "content": f"Answer {sequence}"}]},
                metadata_json={"secret": "PRIVATE_MESSAGE_METADATA"},
                error_json={"secret": "PRIVATE_MESSAGE_ERROR"},
            )
        )
    owner_session = await session_manager.create_session(db, str(owner.id))
    viewer_session = await session_manager.create_session(db, str(viewer.id))
    await db.commit()
    return SharingCase(
        conversation,
        {**bearer_headers(owner_session["session_token"]), "X-Workspace": workspace.slug},
        {**bearer_headers(viewer_session["session_token"]), "X-Workspace": workspace.slug},
        owner_session["session_token"],
        membership,
        workspace,
        owner,
        viewer,
    )


async def set_sharing(client, case, visibility, *, viewer=False):
    return await client.put(
        f"/api/v1/conversations/{case.conversation.id}/sharing",
        headers=case.viewer_headers if viewer else case.owner_headers,
        json={"visibility": visibility},
    )


@pytest.mark.parametrize("role", list(WorkspaceRole))
async def test_every_role_can_share_own_chat_and_read_shared_chat(
    db_session, db_async_client, role
):
    case = await sharing_case(db_session, role=role)
    path = f"/api/v1/conversations/{case.conversation.id}"
    for suffix in ("", "/messages?limit=2", "/messages?limit=2&before_sequence=3"):
        assert (
            await db_async_client.get(path + suffix, headers=case.viewer_headers)
        ).status_code == 404
    shared = await set_sharing(db_async_client, case, "workspace")
    assert shared.status_code == 200, shared.text
    assert shared.json()["access"] == "owner"
    detail = await db_async_client.get(path, headers=case.viewer_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["access"] == "viewer"
    assert detail.json()["capabilities"]["can_reply"] is False
    assert detail.json()["capabilities"]["can_manage_sharing"] is False
    assert detail.json()["capabilities"]["can_stop_sharing"] is (
        role in (WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
    )
    assert "PRIVATE_CONVERSATION_METADATA" not in detail.text
    for before, expected, has_more in ((None, [4, 5], True), (4, [2, 3], True), (2, [1], False)):
        params = {"limit": 2}
        if before is not None:
            params["before_sequence"] = before
        messages = await db_async_client.get(
            path + "/messages", headers=case.viewer_headers, params=params
        )
        assert messages.status_code == 200, messages.text
        body = messages.json()
        assert [message["sequence"] for message in body["messages"]] == expected
        assert body["total"] == 5
        assert body["has_more"] is has_more
        assert "PRIVATE_MESSAGE" not in messages.text
    await db_session.refresh(case.conversation)
    assert case.conversation.unread is True


@pytest.mark.parametrize("role", list(WorkspaceRole))
async def test_only_owner_enables_and_managers_revoke_existing_share(
    db_session, db_async_client, role
):
    case = await sharing_case(db_session, role=role)
    for visibility in ("workspace", "private"):
        assert (
            await set_sharing(db_async_client, case, visibility, viewer=True)
        ).status_code == 404
    assert (await set_sharing(db_async_client, case, "workspace")).status_code == 200
    assert (await set_sharing(db_async_client, case, "workspace", viewer=True)).status_code in (
        403,
        404,
    )
    revoke = await set_sharing(db_async_client, case, "private", viewer=True)
    assert revoke.status_code == (
        200 if role in (WorkspaceRole.OWNER, WorkspaceRole.ADMIN) else 404
    )

    if revoke.status_code == 200:
        assert (await set_sharing(db_async_client, case, "private", viewer=True)).status_code == 404


@pytest.mark.parametrize("role", list(WorkspaceRole))
async def test_other_workspace_membership_grants_no_access(db_session, db_async_client, role):
    case = await sharing_case(db_session, role=role)
    assert (await set_sharing(db_async_client, case, "workspace")).status_code == 200
    other = build_workspace(slug=f"other-sharing-{uuid4().hex}")
    db_session.add_all(
        [
            other,
            build_workspace_membership(workspace_id=other.id, user_id=case.viewer.id, role=role),
        ]
    )
    await db_session.commit()
    headers = {**case.viewer_headers, "X-Workspace": other.slug}
    path = f"/api/v1/conversations/{case.conversation.id}"
    for suffix in ("", "/messages?limit=1", "/messages?limit=1&before_sequence=3"):
        assert (await db_async_client.get(path + suffix, headers=headers)).status_code == 404
    listing = await db_async_client.get(
        "/api/v1/conversations/?scope=workspace_shared", headers=headers
    )
    assert listing.status_code == 200
    assert listing.json()["total"] == 0
    assert (
        await db_async_client.put(
            path + "/sharing", headers=headers, json={"visibility": "private"}
        )
    ).status_code == 404


@pytest.mark.parametrize(
    "loss", ["removed", "inactive_workspace", "anonymous", "deleted", "revoked"]
)
async def test_access_loss_denies_detail_and_every_message_page(db_session, db_async_client, loss):
    case = await sharing_case(db_session)
    assert (await set_sharing(db_async_client, case, "workspace")).status_code == 200
    headers = case.viewer_headers
    if loss == "removed":
        case.membership.deleted = True
    elif loss == "inactive_workspace":
        case.workspace.status = "inactive"
    elif loss == "deleted":
        case.conversation.deleted = True
    elif loss == "revoked":
        assert (await set_sharing(db_async_client, case, "private")).status_code == 200
    else:
        headers = {}
    await db_session.commit()
    path = f"/api/v1/conversations/{case.conversation.id}"
    for suffix in ("", "/messages?limit=2", "/messages?limit=2&before_sequence=3"):
        response = await db_async_client.get(path + suffix, headers=headers)
        assert response.status_code in (401, 403, 404), response.text
        assert "Shared answer" not in response.text
    listing = await db_async_client.get(
        "/api/v1/conversations/?scope=workspace_shared", headers=headers
    )
    if listing.status_code == 200:
        assert listing.json()["total"] == 0
        assert listing.json()["conversations"] == []
    else:
        assert listing.status_code in (401, 403, 404)


@pytest.mark.parametrize("personal,source", [(True, "direct"), (False, "delegated")])
async def test_personal_and_delegated_chats_cannot_be_shared(
    db_session, db_async_client, personal, source
):
    case = await sharing_case(db_session, personal=personal, source=source)
    response = await set_sharing(db_async_client, case, "workspace")
    assert response.status_code in (400, 403, 422), response.text
    for suffix in ("", "/messages", "/messages?before_sequence=3&limit=1"):
        response = await db_async_client.get(
            f"/api/v1/conversations/{case.conversation.id}" + suffix, headers=case.viewer_headers
        )
        assert response.status_code == 404
    listing = await db_async_client.get(
        "/api/v1/conversations/?scope=workspace_shared", headers=case.viewer_headers
    )
    assert listing.json()["total"] == 0


async def test_shared_lists_filter_before_pagination_and_keep_owner_default(
    db_session, db_async_client
):
    case = await sharing_case(db_session)
    assert (await set_sharing(db_async_client, case, "workspace")).status_code == 200
    rows = [
        Conversation(
            user_id=case.owner.id,
            created_by=case.owner.id,
            workspace_id=case.workspace.id,
            title=f"row-{i}",
            visibility=visibility,
            source=source,
            deleted=deleted,
        )
        for i, (visibility, source, deleted) in enumerate(
            [
                ("workspace", "direct", False),
                ("workspace", "direct", True),
                ("private", "direct", False),
                ("private", "delegated", False),
            ]
        )
    ]
    db_session.add_all(rows)
    await db_session.commit()
    listed_ids = []
    for offset in (0, 1, 2):
        response = await db_async_client.get(
            f"/api/v1/conversations/?scope=workspace_shared&limit=1&offset={offset}",
            headers=case.viewer_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 2
        for row in response.json()["conversations"]:
            listed_ids.append(row["id"])
            assert row["access"] == "viewer"
            assert "unread" not in row
            assert "active_run_id" not in row
    assert set(listed_ids) == {str(case.conversation.id), str(rows[0].id)}
    assert len(listed_ids) == 2
    default = await db_async_client.get("/api/v1/conversations/", headers=case.viewer_headers)
    assert default.json()["total"] == 0
    owner_default = await db_async_client.get("/api/v1/conversations/", headers=case.owner_headers)
    assert owner_default.json()["total"] == 3


@pytest.mark.parametrize(
    "method,suffix,payload",
    [
        ("POST", "/read", None),
        ("DELETE", "", None),
        ("GET", "/active-run", None),
        ("POST", "/turns", {"user_prompt": "Unauthorised turn"}),
    ],
)
async def test_viewers_gain_no_owner_execution_or_mutation_routes(
    db_session, db_async_client, method, suffix, payload
):
    case = await sharing_case(db_session)
    assert (await set_sharing(db_async_client, case, "workspace")).status_code == 200
    response = await db_async_client.request(
        method,
        f"/api/v1/conversations/{case.conversation.id}{suffix}",
        headers=case.viewer_headers,
        json=payload,
    )
    assert response.status_code == 404, response.text
    await db_session.refresh(case.conversation)
    assert case.conversation.unread is True
    assert case.conversation.deleted is False


async def test_duplicate_requests_record_only_committed_transitions(db_session, db_async_client):
    case = await sharing_case(db_session)
    for visibility in ("workspace", "workspace", "private", "private"):
        response = await set_sharing(db_async_client, case, visibility)
        assert response.status_code == 200, response.text
    events = list(
        (
            await db_session.scalars(
                select(AuditEvent).where(AuditEvent.resource_id == str(case.conversation.id))
            )
        ).all()
    )
    assert len(events) == 2
    assert {
        (event.details["previous_visibility"], event.details["visibility"]) for event in events
    } == {("private", "workspace"), ("workspace", "private")}
    assert all(
        event.actor_user_id == case.owner.id and event.workspace_id == case.workspace.id
        for event in events
    )
    await db_session.refresh(case.conversation)
    assert case.conversation.visibility == "private"
    assert case.conversation.shared_at is None
    assert case.conversation.shared_by_user_id is None


@pytest.mark.parametrize("source", ["direct", "scheduled", "event", "delegated"])
async def test_every_conversation_source_defaults_to_private(db_session, source):
    case = await sharing_case(db_session, source=source)
    assert case.conversation.visibility == "private"
    assert case.conversation.shared_at is None
    assert case.conversation.shared_by_user_id is None


async def test_audit_failure_rolls_back_visibility(db_session, db_async_client, monkeypatch):
    import importlib

    from services.conversations.update_sharing import update_conversation_sharing

    case = await sharing_case(db_session)
    conversation_id = case.conversation.id
    module = importlib.import_module("services.conversations.update_sharing")

    async def fail_audit(*args, **kwargs):
        raise RuntimeError("Audit unavailable")

    monkeypatch.setattr(module, "record_operation_audit_event", fail_audit)
    with pytest.raises(RuntimeError, match="Audit unavailable"):
        async with db_session.begin_nested():
            await update_conversation_sharing(
                db_session,
                actor=case.owner,
                workspace=case.workspace,
                conversation_id=conversation_id,
                visibility="workspace",
            )
    await db_session.refresh(case.conversation)
    assert case.conversation.visibility == "private"
    assert case.conversation.shared_at is None
    assert not list(
        await db_session.scalars(
            select(AuditEvent).where(AuditEvent.resource_id == str(conversation_id))
        )
    )


@pytest.mark.parametrize("race", ["duplicate", "revoke", "delete"])
async def test_concurrent_sharing_transitions_are_serialised(committed_db_session_factory, race):
    import asyncio

    from core.exceptions.general import NotFoundError
    from services.conversations.delete_conversation import delete_conversation
    from services.conversations.update_sharing import update_conversation_sharing

    async with committed_db_session_factory() as setup:
        case = await sharing_case(setup)
        conversation_id = case.conversation.id
        if race != "duplicate":
            await update_conversation_sharing(
                setup,
                actor=case.owner,
                workspace=case.workspace,
                conversation_id=conversation_id,
                visibility="workspace",
            )
            await setup.commit()
    ready = asyncio.Event()
    arrivals = 0

    async def mutate(operation):
        nonlocal arrivals
        async with committed_db_session_factory() as db:
            arrivals += 1
            if arrivals == 2:
                ready.set()
            await asyncio.wait_for(ready.wait(), timeout=5)
            try:
                if operation == "delete":
                    await delete_conversation(
                        db,
                        actor=case.owner,
                        workspace=case.workspace,
                        conversation_id=conversation_id,
                    )
                else:
                    await update_conversation_sharing(
                        db,
                        actor=case.owner,
                        workspace=case.workspace,
                        conversation_id=conversation_id,
                        visibility=operation,
                    )
                await db.commit()
                return "committed"
            except NotFoundError:
                await db.rollback()
                return "unavailable"

    second = {"duplicate": "workspace", "revoke": "private", "delete": "delete"}[race]
    results = await asyncio.gather(mutate("workspace"), mutate(second))
    async with committed_db_session_factory() as db:
        conversation = await db.get(Conversation, conversation_id)
        events = list(
            await db.scalars(
                select(AuditEvent)
                .where(AuditEvent.resource_id == str(conversation_id))
                .order_by(AuditEvent.occurred_at, AuditEvent.id)
            )
        )
        if race == "duplicate":
            assert results == ["committed", "committed"]
            assert conversation.visibility == "workspace"
            assert len(events) == 1
        elif race == "delete":
            assert conversation.deleted is True
            assert len(events) == 1
        else:
            assert results == ["committed", "committed"]
            assert len(events) in (2, 3)
            assert conversation.visibility == ("private" if len(events) == 2 else "workspace")
        previous = "private"
        for event in events:
            assert event.details["previous_visibility"] == previous
            assert event.details["visibility"] != previous
            previous = event.details["visibility"]
        assert conversation.visibility == previous


@pytest.mark.parametrize("visibility,source", [("public", "direct"), ("workspace", "delegated")])
async def test_database_rejects_invalid_visibility(db_session, visibility, source):
    from sqlalchemy.exc import IntegrityError

    case = await sharing_case(db_session)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            case.conversation.visibility = visibility
            case.conversation.source = source
            await db_session.flush()


@pytest.mark.parametrize("role", list(WorkspaceRole))
async def test_shared_run_approvals_and_context_remain_owner_only(
    db_session, db_async_client, role
):
    from models.agent import Agent
    from models.agent_run import AgentRun

    case = await sharing_case(db_session, role=role)
    agent = Agent(
        name="Sharing test",
        slug=f"sharing-{uuid4().hex}",
        instructions="Test",
        workspace_id=case.workspace.id,
        created_by=case.owner.id,
    )
    db_session.add(agent)
    await db_session.flush()
    run = AgentRun(
        conversation_id=case.conversation.id,
        agent_id=agent.id,
        workspace_id=case.workspace.id,
        user_id=case.owner.id,
        trigger="interactive",
        status="awaiting_approval",
    )
    db_session.add(run)
    await db_session.commit()
    assert (await set_sharing(db_async_client, case, "workspace")).status_code == 200
    approval_path = f"/api/v1/agent-runs/{run.id}"
    assert (
        await db_async_client.get(approval_path + "/approval-state", headers=case.viewer_headers)
    ).status_code == 404
    resume = await db_async_client.post(
        approval_path + "/resume",
        headers=case.viewer_headers,
        json={"decisions": [{"tool_call_id": "pending", "decision": "approved"}]},
    )
    assert resume.status_code == 404, resume.text
    context_path = f"/api/v1/integrations/conversations/{case.conversation.id}/context"
    assert (await db_async_client.get(context_path, headers=case.viewer_headers)).status_code == 404
    assert (
        await db_async_client.put(context_path, headers=case.viewer_headers, json={"targets": []})
    ).status_code == 404
    assert (
        await db_async_client.delete(context_path, headers=case.viewer_headers)
    ).status_code == 404
    detail = await db_async_client.get(
        f"/api/v1/conversations/{case.conversation.id}", headers=case.viewer_headers
    )
    assert detail.status_code == 200
    await db_session.refresh(run)
    assert run.status == "awaiting_approval"
    cancelled = await db_async_client.post(approval_path + "/cancel", headers=case.viewer_headers)
    assert cancelled.status_code == (
        200 if role in (WorkspaceRole.OWNER, WorkspaceRole.ADMIN) else 403
    ), cancelled.text


async def test_owner_departure_preserves_shared_answer_but_prevents_owner_changes(
    db_session, db_async_client
):
    from models.workspace import WorkspaceMembership

    case = await sharing_case(db_session)
    assert (await set_sharing(db_async_client, case, "workspace")).status_code == 200
    membership = await db_session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.user_id == case.owner.id,
            WorkspaceMembership.workspace_id == case.workspace.id,
        )
    )
    membership.deleted = True
    await db_session.commit()
    path = f"/api/v1/conversations/{case.conversation.id}"
    assert (await db_async_client.get(path, headers=case.viewer_headers)).status_code == 200
    assert (
        await db_async_client.get(path + "/messages", headers=case.viewer_headers)
    ).status_code == 200
    assert (await set_sharing(db_async_client, case, "private")).status_code in (403, 404)


@pytest.mark.parametrize("source", ["direct", "scheduled", "event", "delegated"])
async def test_database_default_keeps_all_sources_private(db_session, source):
    from sqlalchemy import text

    case = await sharing_case(db_session)
    result = await db_session.execute(
        text(
            "INSERT INTO conversations (id, user_id, created_by, workspace_id, source) VALUES (:id, :user, :user, :workspace, :source) RETURNING visibility, shared_at, shared_by_user_id"
        ),
        {"id": uuid4(), "user": case.owner.id, "workspace": case.workspace.id, "source": source},
    )
    assert tuple(result.one()) == ("private", None, None)
