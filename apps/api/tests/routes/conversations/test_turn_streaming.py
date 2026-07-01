# apps/api/tests/routes/conversations/test_turn_streaming.py

"""Route tests for conversation turn streaming and heal reads."""

import asyncio
import importlib
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic_ai import DeferredToolRequests
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.auth.sessions import session_manager
from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation, ConversationMessage
from models.session import Session
from models.user import User
from models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from services.agent_runs import (
    complete_agent_run,
    create_agent_run,
    mark_run_awaiting_approval,
    start_agent_run,
)
from services.agents.models.domain import ModelConfigurationError
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.events import (
    EVENT_CONVERSATION_CREATED,
    EVENT_CONVERSATION_UPDATED,
    EVENT_DONE,
    EVENT_RUN_STATUS,
    EVENT_TOOL_CALL,
    EVENT_TOOL_RESULT,
    STREAM_PROTOCOL_VERSION,
    STREAM_VERSION_HEADER,
)
from services.agents.runtime.execute_run import execute_run
from services.agents.runtime.sinks import CollectingSink, EventSink
from services.conversations.create_turn_stream import create_conversation_turn_stream
from services.conversations.schemas import ConversationTurnCreateRequest
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers

pytestmark = pytest.mark.asyncio


async def _authenticated_context(
    db: AsyncSession,
) -> tuple[User, Workspace, Agent, Conversation, dict[str, str]]:
    user = build_user(email=f"turn-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"turn-{uuid4().hex[:8]}")
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.OWNER,
    )
    db.add_all([user, workspace, membership])
    await db.flush()
    user.default_workspace_id = workspace.id

    agent = Agent(
        name="Turn Agent",
        slug=f"turn-agent-{uuid4().hex[:8]}",
        instructions="Reply plainly.",
        workspace_id=workspace.id,
        created_by=user.id,
        model_provider="openai",
        model="gpt-5.4-mini",
    )
    db.add(agent)
    await db.flush()

    conversation = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
        active_agent_id=agent.id,
    )
    db.add(conversation)
    session = await session_manager.create_session(db, str(user.id))
    await db.commit()
    return user, workspace, agent, conversation, bearer_headers(session["session_token"])


async def test_create_turn_stream_returns_ordered_sse_events(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _user, _workspace, _agent, conversation, headers = await _authenticated_context(db_session)

    async def fake_worker(
        *,
        run_id: UUID,
        conversation_id: UUID,
        user_prompt: str,
        sink: EventSink,
        client_message_id: str | None = None,
        model=None,
    ) -> None:
        assert user_prompt == "Hello"
        assert client_message_id == "client-1"
        await sink.emit(EVENT_RUN_STATUS, {"status": "running"})
        await sink.emit(EVENT_DONE, {"status": "completed"})
        await sink.close()

    monkeypatch.setattr(
        "services.conversations.create_turn_stream.run_turn_worker",
        fake_worker,
    )

    async with db_async_client.stream(
        "POST",
        f"/api/v1/conversations/{conversation.id}/turns",
        headers=headers,
        json={"user_prompt": "Hello", "client_message_id": "client-1"},
    ) as response:
        body = (await response.aread()).decode()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers[STREAM_VERSION_HEADER] == STREAM_PROTOCOL_VERSION
    assert body.index('"status":"pending"') < body.index('"status":"running"')
    assert "event: done" in body


async def test_create_conversation_stream_creates_conversation_and_first_run(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _user, _workspace, agent, _existing_conversation, headers = await _authenticated_context(
        db_session
    )

    async def fake_title_worker(
        *,
        conversation_id: UUID,
        user_prompt: str,
        fallback_title: str,
        sink: EventSink,
    ) -> None:
        assert user_prompt == "Plan the launch"
        assert fallback_title == "Plan the launch"
        conversation = await db_session.get(Conversation, conversation_id)
        assert conversation is not None
        conversation.title = "Launch planning"
        conversation.metadata_json = {"title": {"source": "model", "model": "function:title"}}
        await db_session.flush()
        await sink.emit(
            EVENT_CONVERSATION_UPDATED,
            {
                "conversation": {
                    "id": str(conversation.id),
                    "title": "Launch planning",
                    "active_agent_id": str(agent.id),
                    "agent_slug": agent.slug,
                }
            },
        )

    async def fake_worker(
        *,
        run_id: UUID,
        conversation_id: UUID,
        user_prompt: str,
        sink: EventSink,
        client_message_id: str | None = None,
        model=None,
    ) -> None:
        assert user_prompt == "Plan the launch"
        assert client_message_id == "first-message"
        await sink.emit(EVENT_RUN_STATUS, {"status": "running"})
        await sink.emit(EVENT_DONE, {"status": "completed"})
        await sink.close()

    # Patch the module object directly: the services.conversations package re-exports a
    # same-named create_conversation_stream function that shadows the submodule, so a
    # string target would resolve to the function instead of the module.
    create_conversation_stream_module = importlib.import_module(
        "services.conversations.create_conversation_stream"
    )
    monkeypatch.setattr(
        create_conversation_stream_module,
        "run_conversation_title_worker",
        fake_title_worker,
    )
    monkeypatch.setattr(
        create_conversation_stream_module,
        "run_turn_worker",
        fake_worker,
    )

    async with db_async_client.stream(
        "POST",
        "/api/v1/conversations/",
        headers=headers,
        json={
            "agent_id": str(agent.id),
            "user_prompt": "Plan the launch",
            "client_message_id": "first-message",
        },
    ) as response:
        body = (await response.aread()).decode()

    await _drain_initial_conversation_background_work()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers[STREAM_VERSION_HEADER] == STREAM_PROTOCOL_VERSION
    assert body.index(f"event: {EVENT_CONVERSATION_CREATED}") < body.index(
        f"event: {EVENT_RUN_STATUS}"
    )
    assert '"title":"Plan the launch"' in body
    assert '"title":"Launch planning"' in body
    assert f'"active_agent_id":"{agent.id}"' in body
    assert f'"agent_slug":"{agent.slug}"' in body
    assert "event: done" in body

    created_conversation = await db_session.scalar(
        select(Conversation)
        .where(
            Conversation.active_agent_id == agent.id,
            Conversation.title == "Launch planning",
        )
        .order_by(Conversation.created_at.desc())
    )
    assert created_conversation is not None
    assert created_conversation.agent_slug == agent.slug
    assert created_conversation.metadata_json == {
        "title": {"source": "model", "model": "function:title"}
    }
    created_run = await db_session.scalar(
        select(AgentRun).where(AgentRun.conversation_id == created_conversation.id)
    )
    assert created_run is not None
    assert created_run.agent_id == agent.id
    assert created_run.status == "pending"
    assert created_run.metadata_json == {"client_message_id": "first-message"}


async def test_create_conversation_rejects_inactive_agent_without_creating_run(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _user, _workspace, agent, existing_conversation, headers = await _authenticated_context(
        db_session
    )
    agent.is_active = False
    await db_session.commit()

    response = await db_async_client.post(
        "/api/v1/conversations/",
        headers=headers,
        json={
            "agent_id": str(agent.id),
            "user_prompt": "Plan the launch",
        },
    )

    assert response.status_code == 409
    body: Mapping[str, object] = response.json()
    assert body["conflicting_resource"] == "agent"
    assert body["agent_id"] == str(agent.id)

    runs = (
        await db_session.scalars(
            select(AgentRun).where(AgentRun.conversation_id == existing_conversation.id)
        )
    ).all()
    assert runs == []


async def test_create_conversation_runtime_failure_prunes_empty_conversation(
    app: FastAPI,
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with committed_db_session_factory() as db:
        user, workspace, agent, _existing_conversation, headers = await _authenticated_context(db)

    def broken_model(_resolved_model):
        raise ModelConfigurationError("Missing credential", details={"provider": "openai"})

    monkeypatch.setattr("services.agents.runtime.loop.build_model", broken_model)

    try:
        transport = ASGITransport(app=app)
        async with (
            AsyncClient(transport=transport, base_url="http://testserver") as client,
            client.stream(
                "POST",
                "/api/v1/conversations/",
                headers=headers,
                json={
                    "agent_id": str(agent.id),
                    "user_prompt": "Please fail before saving messages",
                },
            ) as response,
        ):
            body = (await response.aread()).decode()

        assert response.status_code == 200
        assert "event: error" in body
        assert "event: done" in body

        await _drain_initial_conversation_background_work()
        await _wait_for_non_deleted_conversation_count(
            committed_db_session_factory,
            user_id=user.id,
            workspace_id=workspace.id,
            count=1,
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            list_response = await client.get("/api/v1/conversations/", headers=headers)

        assert list_response.status_code == 200
        assert list_response.json()["total"] == 1

        async with committed_db_session_factory() as db:
            pruned = await db.scalar(
                select(Conversation).where(
                    Conversation.user_id == user.id,
                    Conversation.workspace_id == workspace.id,
                    Conversation.title == "Please fail before saving messages",
                    Conversation.deleted == True,  # noqa: E712
                )
            )
            assert pruned is not None
    finally:
        try:
            await _drain_initial_conversation_background_work()
        finally:
            await _delete_committed_workspace_context(
                committed_db_session_factory,
                user_id=user.id,
                workspace_id=workspace.id,
            )


async def test_list_conversations_returns_current_user_workspace_conversations(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, agent, existing_conversation, headers = await _authenticated_context(
        db_session
    )
    existing_conversation.title = "Existing"
    existing_conversation.agent_slug = agent.slug
    existing_conversation.unread = True
    older = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
        title="Older",
        active_agent_id=agent.id,
        agent_slug=agent.slug,
        last_message_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    newest = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
        title="Newest",
        active_agent_id=agent.id,
        agent_slug=agent.slug,
        last_message_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    deleted = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
        title="Deleted",
        active_agent_id=agent.id,
        agent_slug=agent.slug,
    )
    deleted.soft_delete(deleted_by=user.id, cascade=False)
    db_session.add_all([older, newest, deleted])
    await db_session.flush()
    active_run = await create_agent_run(
        db_session,
        conversation_id=newest.id,
        agent_id=agent.id,
        workspace_id=workspace.id,
        user_id=user.id,
        trigger="interactive",
    )
    await start_agent_run(db_session, active_run)
    await mark_run_awaiting_approval(db_session, active_run)
    await db_session.commit()

    response = await db_async_client.get(
        "/api/v1/conversations/",
        headers=headers,
        params={"limit": 10, "offset": 0},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 10
    assert body["offset"] == 0
    assert [conversation["title"] for conversation in body["conversations"]] == [
        "Existing",
        "Newest",
        "Older",
    ]
    assert all(
        conversation["active_agent_id"] == str(agent.id) for conversation in body["conversations"]
    )
    assert all(conversation["agent_name"] == agent.name for conversation in body["conversations"])

    by_title = {conversation["title"]: conversation for conversation in body["conversations"]}
    assert by_title["Existing"]["unread"] is True
    assert by_title["Existing"]["active_run_id"] is None
    assert by_title["Existing"]["needs_approval"] is False
    assert by_title["Newest"]["active_run_id"] == str(active_run.id)
    assert by_title["Newest"]["active_run_status"] == "awaiting_approval"
    assert by_title["Newest"]["needs_approval"] is True


async def test_mark_conversation_read_is_idempotent_for_owner(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _user, _workspace, agent, conversation, headers = await _authenticated_context(db_session)
    conversation.title = "Unread thread"
    conversation.agent_slug = agent.slug
    conversation.unread = True
    await db_session.commit()

    response = await db_async_client.post(
        f"/api/v1/conversations/{conversation.id}/read",
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(conversation.id)
    assert body["unread"] is False
    assert body["agent_name"] == agent.name

    await db_session.refresh(conversation)
    assert conversation.unread is False

    second_response = await db_async_client.post(
        f"/api/v1/conversations/{conversation.id}/read",
        headers=headers,
    )

    assert second_response.status_code == 200
    assert second_response.json()["unread"] is False


async def test_mark_conversation_read_rejects_other_workspace_user(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _user, _workspace, _agent, conversation, _headers = await _authenticated_context(db_session)
    conversation.unread = True
    (
        _other_user,
        _other_workspace,
        _other_agent,
        _other_conversation,
        other_headers,
    ) = await _authenticated_context(db_session)
    await db_session.commit()

    response = await db_async_client.post(
        f"/api/v1/conversations/{conversation.id}/read",
        headers=other_headers,
    )

    assert response.status_code == 404
    await db_session.refresh(conversation)
    assert conversation.unread is True


async def test_delete_conversation_soft_deletes_and_hides_conversation(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, _workspace, _agent, conversation, headers = await _authenticated_context(db_session)

    response = await db_async_client.delete(
        f"/api/v1/conversations/{conversation.id}",
        headers=headers,
    )

    assert response.status_code == 204
    await db_session.refresh(conversation)
    assert conversation.deleted is True
    assert conversation.deleted_by == user.id

    list_response = await db_async_client.get("/api/v1/conversations/", headers=headers)
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 0

    messages_response = await db_async_client.get(
        f"/api/v1/conversations/{conversation.id}/messages",
        headers=headers,
    )
    assert messages_response.status_code == 404


async def test_delete_conversation_rejects_active_run(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, agent, conversation, headers = await _authenticated_context(db_session)
    active_run = await create_agent_run(
        db_session,
        conversation_id=conversation.id,
        agent_id=agent.id,
        workspace_id=workspace.id,
        user_id=user.id,
        trigger="interactive",
    )
    await start_agent_run(db_session, active_run)
    await db_session.commit()

    response = await db_async_client.delete(
        f"/api/v1/conversations/{conversation.id}",
        headers=headers,
    )

    assert response.status_code == 409
    body: Mapping[str, object] = response.json()
    assert body["conflicting_resource"] == "agent_run"
    assert body["active_run_id"] == str(active_run.id)

    await db_session.refresh(conversation)
    assert conversation.deleted is False


async def test_create_turn_stream_disconnect_completes_and_persists_with_real_worker(
    app: FastAPI,
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with committed_db_session_factory() as db:
        user, workspace, _agent, conversation, headers = await _authenticated_context(db)

    stream_entered = asyncio.Event()
    release_stream = asyncio.Event()

    async def delayed_stream(_messages, _agent_info):
        stream_entered.set()
        await release_stream.wait()
        yield "route reply"

    monkeypatch.setattr(
        "services.agents.runtime.loop.build_model",
        lambda _resolved_model: FunctionModel(
            stream_function=delayed_stream,
            model_name="route-delayed",
        ),
    )

    try:
        async with committed_db_session_factory() as db:
            response = await create_conversation_turn_stream(
                db,
                actor=user,
                workspace=workspace,
                conversation_id=conversation.id,
                payload=ConversationTurnCreateRequest(
                    user_prompt="Hello",
                    client_message_id="disconnect-test",
                ),
            )

        assert response.status_code == 200
        body_iterator = response.body_iterator
        first_frame = await anext(body_iterator)
        assert "event: run.status" in first_frame
        await asyncio.wait_for(stream_entered.wait(), timeout=2)
        await body_iterator.aclose()

        release_stream.set()
        await _wait_for_run_status(
            committed_db_session_factory,
            conversation_id=conversation.id,
            status="completed",
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            messages_response = await client.get(
                f"/api/v1/conversations/{conversation.id}/messages",
                headers=headers,
            )

        assert messages_response.status_code == 200
        messages = messages_response.json()["messages"]
        assert [message["role"] for message in messages] == ["user", "assistant"]
        assert messages[0]["client_message_id"] == "disconnect-test"
    finally:
        release_stream.set()
        await _delete_committed_context(
            committed_db_session_factory,
            user_id=user.id,
            workspace_id=workspace.id,
            agent_id=conversation.active_agent_id,
            conversation_id=conversation.id,
        )


async def test_create_turn_reaps_stale_run_then_admits_new_turn_with_real_worker(
    app: FastAPI,
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with committed_db_session_factory() as db:
        user, workspace, agent, conversation, headers = await _authenticated_context(db)
        stale_run = await create_agent_run(
            db,
            conversation_id=conversation.id,
            agent_id=agent.id,
            workspace_id=workspace.id,
            user_id=user.id,
            trigger="interactive",
        )
        await start_agent_run(db, stale_run)
        stale_run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()

    async def quick_stream(_messages, _agent_info):
        yield "fresh reply"

    monkeypatch.setattr(
        "services.agents.runtime.loop.build_model",
        lambda _resolved_model: FunctionModel(
            stream_function=quick_stream,
            model_name="route-quick",
        ),
    )

    try:
        transport = ASGITransport(app=app)
        async with (
            AsyncClient(transport=transport, base_url="http://testserver") as client,
            client.stream(
                "POST",
                f"/api/v1/conversations/{conversation.id}/turns",
                headers=headers,
                json={"user_prompt": "Hello"},
            ) as response,
        ):
            body = (await response.aread()).decode()

        assert response.status_code == 200
        assert "event: done" in body

        async with committed_db_session_factory() as db:
            runs = (
                await db.scalars(
                    select(AgentRun)
                    .where(AgentRun.conversation_id == conversation.id)
                    .order_by(AgentRun.created_at)
                )
            ).all()
            assert [run.status for run in runs] == ["failed", "completed"]
            assert runs[0].id == stale_run.id
    finally:
        await _delete_committed_context(
            committed_db_session_factory,
            user_id=user.id,
            workspace_id=workspace.id,
            agent_id=agent.id,
            conversation_id=conversation.id,
        )


async def test_create_turn_rejects_existing_active_run(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, agent, conversation, headers = await _authenticated_context(db_session)
    active_run = await create_agent_run(
        db_session,
        conversation_id=conversation.id,
        agent_id=agent.id,
        workspace_id=workspace.id,
        user_id=user.id,
        trigger="interactive",
    )
    await start_agent_run(db_session, active_run)
    await db_session.commit()

    response = await db_async_client.post(
        f"/api/v1/conversations/{conversation.id}/turns",
        headers=headers,
        json={"user_prompt": "Hello"},
    )

    assert response.status_code == 409
    body: Mapping[str, object] = response.json()
    assert body["active_run_id"] == str(active_run.id)


async def test_create_turn_rejects_duplicate_completed_client_message_id(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, agent, conversation, headers = await _authenticated_context(db_session)
    completed_run = await create_agent_run(
        db_session,
        conversation_id=conversation.id,
        agent_id=agent.id,
        workspace_id=workspace.id,
        user_id=user.id,
        trigger="interactive",
    )
    await start_agent_run(db_session, completed_run)
    await complete_agent_run(db_session, completed_run)
    existing_message = ConversationMessage(
        conversation_id=conversation.id,
        role="user",
        parts={"kind": "request", "parts": []},
        metadata_json={"source": "pydantic_ai", "agent_run_id": str(completed_run.id)},
        sequence=1,
        client_message_id="client-duplicate",
    )
    db_session.add(existing_message)
    await db_session.commit()

    response = await db_async_client.post(
        f"/api/v1/conversations/{conversation.id}/turns",
        headers=headers,
        json={"user_prompt": "Hello again", "client_message_id": "client-duplicate"},
    )

    assert response.status_code == 409
    body: Mapping[str, object] = response.json()
    assert body["conflicting_resource"] == "conversation_message"
    assert body["client_message_id"] == "client-duplicate"
    assert body["existing_message_id"] == str(existing_message.id)
    assert body["existing_agent_run_id"] == str(completed_run.id)

    runs = (
        await db_session.scalars(
            select(AgentRun).where(AgentRun.conversation_id == conversation.id)
        )
    ).all()
    assert [run.id for run in runs] == [completed_run.id]


async def test_get_active_run_lazily_reaps_expired_run(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    from datetime import UTC, datetime, timedelta

    user, workspace, agent, conversation, headers = await _authenticated_context(db_session)
    run = await create_agent_run(
        db_session,
        conversation_id=conversation.id,
        agent_id=agent.id,
        workspace_id=workspace.id,
        user_id=user.id,
        trigger="interactive",
    )
    await start_agent_run(db_session, run)
    run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    response = await db_async_client.get(
        f"/api/v1/conversations/{conversation.id}/active-run",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["active_run"] is None

    stored = await db_session.get(AgentRun, run.id)
    assert stored is not None
    await db_session.refresh(stored)
    assert stored.status == "failed"


async def test_resume_run_rejects_run_not_awaiting_approval(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, agent, conversation, headers = await _authenticated_context(db_session)
    run = await create_agent_run(
        db_session,
        conversation_id=conversation.id,
        agent_id=agent.id,
        workspace_id=workspace.id,
        user_id=user.id,
        trigger="interactive",
    )
    await db_session.commit()

    response = await db_async_client.post(
        f"/api/v1/agent-runs/{run.id}/resume",
        headers=headers,
        json={
            "decisions": [
                {"tool_call_id": "tool-call-1", "decision": "approved"},
            ],
        },
    )

    assert response.status_code == 409
    body: Mapping[str, object] = response.json()
    assert body["conflicting_resource"] == "agent_run"
    assert body["run_status"] == "pending"


async def test_resume_run_streams_approved_tool_to_completion(
    app: FastAPI,
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "services.agents.runtime.loop.build_model",
        lambda _resolved_model: TestModel(),
    )
    async with committed_db_session_factory() as db:
        user, workspace, agent, conversation, headers = await _authenticated_context(db)
        agent.tool_names = ["add_numbers"]
        agent.tool_policies = {"add_numbers": "approval"}
        run = await create_agent_run(
            db,
            conversation_id=conversation.id,
            agent_id=agent.id,
            workspace_id=workspace.id,
            user_id=user.id,
            trigger="interactive",
        )
        suspended = await execute_run(
            db,
            conversation_id=conversation.id,
            run_id=run.id,
            user_prompt="Add two numbers",
            sink=CollectingSink(run_id=run.id, conversation_id=conversation.id),
            model=TestModel(),
        )
        assert isinstance(suspended.output, DeferredToolRequests)

        stored_run = await db.get(AgentRun, run.id)
        assert stored_run is not None
        tool_call_id = load_suspended_run_state(stored_run).pending_tool_call_ids[0]

    try:
        transport = ASGITransport(app=app)
        async with (
            AsyncClient(transport=transport, base_url="http://testserver") as client,
            client.stream(
                "POST",
                f"/api/v1/agent-runs/{run.id}/resume",
                headers=headers,
                json={
                    "decisions": [
                        {
                            "tool_call_id": tool_call_id,
                            "decision": "approved",
                            "override_args": {"a": 4, "b": 7},
                        },
                    ],
                },
            ) as response,
        ):
            body = (await response.aread()).decode()

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers[STREAM_VERSION_HEADER] == STREAM_PROTOCOL_VERSION
        assert f"event: {EVENT_RUN_STATUS}" in body
        assert '"status":"awaiting_approval"' in body
        assert f"event: {EVENT_TOOL_CALL}" in body
        assert f"event: {EVENT_TOOL_RESULT}" in body
        assert f'"tool_call_id":"{tool_call_id}"' in body
        assert '"args":{"a":4,"b":7}' in body
        assert '"result":11' in body
        assert f"event: {EVENT_DONE}" in body
        assert '"status":"completed"' in body

        async with committed_db_session_factory() as db:
            stored_run = await db.get(AgentRun, run.id)
            assert stored_run is not None
            assert stored_run.status == "completed"

            messages = (
                await db.scalars(
                    select(ConversationMessage)
                    .where(ConversationMessage.conversation_id == conversation.id)
                    .order_by(ConversationMessage.sequence)
                )
            ).all()
            assert [message.role for message in messages] == [
                "user",
                "assistant",
                "tool",
                "assistant",
            ]
            assert "11" in str(messages[2].parts)
    finally:
        await _delete_committed_context(
            committed_db_session_factory,
            user_id=user.id,
            workspace_id=workspace.id,
            agent_id=agent.id,
            conversation_id=conversation.id,
        )


async def _wait_for_run_status(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    conversation_id: UUID,
    status: str,
    timeout_seconds: float = 3,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        async with session_factory() as db:
            found = await db.scalar(
                select(AgentRun.id).where(
                    AgentRun.conversation_id == conversation_id,
                    AgentRun.status == status,
                )
            )
            if found is not None:
                return
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"Timed out waiting for run status {status!r}")
        await asyncio.sleep(0.05)


async def _wait_for_non_deleted_conversation_count(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: UUID,
    workspace_id: UUID,
    count: int,
    timeout_seconds: float = 3,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        async with session_factory() as db:
            conversations = (
                await db.scalars(
                    select(Conversation).where(
                        Conversation.user_id == user_id,
                        Conversation.workspace_id == workspace_id,
                        Conversation.deleted == False,  # noqa: E712
                    )
                )
            ).all()
            if len(conversations) == count:
                return
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"Timed out waiting for {count} non-deleted conversations")
        await asyncio.sleep(0.05)


async def _drain_initial_conversation_background_work(
    *,
    max_wait_seconds: float = 3,
) -> None:
    from services.agents.runtime.run_manager import run_task_registry

    await run_task_registry.drain(max_wait_seconds=max_wait_seconds)

    create_conversation_stream_module = importlib.import_module(
        "services.conversations.create_conversation_stream"
    )
    title_tasks = [
        task
        for task in create_conversation_stream_module._background_title_tasks
        if not task.done()
    ]
    if not title_tasks:
        return

    done, pending = await asyncio.wait(title_tasks, timeout=max_wait_seconds)
    for task in done:
        task.result()
    if pending:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        raise AssertionError(f"Timed out waiting for {len(pending)} conversation title task(s)")


async def _delete_committed_workspace_context(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: UUID,
    workspace_id: UUID,
) -> None:
    async with session_factory() as db:
        conversation_ids = (
            await db.scalars(
                select(Conversation.id).where(
                    Conversation.user_id == user_id,
                    Conversation.workspace_id == workspace_id,
                )
            )
        ).all()
        if conversation_ids:
            await db.execute(
                delete(ConversationMessage).where(
                    ConversationMessage.conversation_id.in_(conversation_ids)
                )
            )
            await db.execute(delete(AgentRun).where(AgentRun.conversation_id.in_(conversation_ids)))
            await db.execute(delete(Conversation).where(Conversation.id.in_(conversation_ids)))
        await db.execute(delete(Agent).where(Agent.workspace_id == workspace_id))
        await db.execute(
            delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace_id)
        )
        await db.execute(delete(Session).where(Session.user_id == user_id))
        await db.execute(update(User).where(User.id == user_id).values(default_workspace_id=None))
        await db.execute(delete(User).where(User.id == user_id))
        await db.execute(delete(Workspace).where(Workspace.id == workspace_id))
        await db.commit()


async def _delete_committed_context(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: UUID,
    workspace_id: UUID,
    agent_id: UUID | None,
    conversation_id: UUID,
) -> None:
    async with session_factory() as db:
        await db.execute(
            delete(ConversationMessage).where(
                ConversationMessage.conversation_id == conversation_id
            )
        )
        await db.execute(delete(AgentRun).where(AgentRun.conversation_id == conversation_id))
        await db.execute(delete(Conversation).where(Conversation.id == conversation_id))
        if agent_id is not None:
            await db.execute(delete(Agent).where(Agent.id == agent_id))
        await db.execute(
            delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace_id)
        )
        await db.execute(delete(Session).where(Session.user_id == user_id))
        await db.execute(update(User).where(User.id == user_id).values(default_workspace_id=None))
        await db.execute(delete(User).where(User.id == user_id))
        await db.execute(delete(Workspace).where(Workspace.id == workspace_id))
        await db.commit()
