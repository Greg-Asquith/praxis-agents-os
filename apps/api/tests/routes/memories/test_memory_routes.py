# apps/api/tests/routes/memories/test_memory_routes.py

"""HTTP-boundary tests for the human memory-management surface."""

from dataclasses import dataclass
from importlib import import_module
from uuid import uuid4

from httpx2 import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from models.agent import Agent
from models.agent_memories import AgentMemory
from models.audit_event import AuditEvent
from models.user import User
from models.workspace import Workspace, WorkspaceRole
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers


@dataclass(frozen=True)
class RouteActor:
    user: User
    headers: dict[str, str]


async def test_read_only_can_list_but_cannot_mutate(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    workspace, agent = await _workspace_with_agent(db_session)
    reader = await _actor(db_session, workspace=workspace, role=WorkspaceRole.READ_ONLY)
    memory = _memory(workspace=workspace, agent=agent, user=reader.user)
    db_session.add(memory)
    await db_session.commit()

    listed = await db_async_client.get("/api/v1/memories/", headers=reader.headers)
    updated = await db_async_client.patch(
        f"/api/v1/memories/{memory.id}",
        headers=reader.headers,
        json={"importance": 5},
    )
    deleted = await db_async_client.delete(
        f"/api/v1/memories/{memory.id}",
        headers=reader.headers,
    )

    assert listed.status_code == 200
    assert listed.json()["memories"][0]["id"] == str(memory.id)
    assert updated.status_code == 403
    assert deleted.status_code == 403


async def test_user_scope_is_hidden_from_other_members_on_every_operation(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    workspace, agent = await _workspace_with_agent(db_session)
    owner = await _actor(db_session, workspace=workspace, role=WorkspaceRole.MEMBER)
    other = await _actor(db_session, workspace=workspace, role=WorkspaceRole.MEMBER)
    memory = _memory(
        workspace=workspace,
        agent=agent,
        user=owner.user,
        scope="user",
    )
    db_session.add(memory)
    await db_session.commit()

    listed = await db_async_client.get("/api/v1/memories/", headers=other.headers)
    fetched = await db_async_client.get(
        f"/api/v1/memories/{memory.id}",
        headers=other.headers,
    )
    updated = await db_async_client.patch(
        f"/api/v1/memories/{memory.id}",
        headers=other.headers,
        json={"importance": 5},
    )
    deleted = await db_async_client.delete(
        f"/api/v1/memories/{memory.id}",
        headers=other.headers,
    )

    assert listed.status_code == 200
    assert listed.json()["memories"] == []
    assert fetched.status_code == 404
    assert updated.status_code == 404
    assert deleted.status_code == 404


async def test_member_edits_agent_memory_but_cannot_delete_workspace_memory(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    workspace, agent = await _workspace_with_agent(db_session)
    member = await _actor(db_session, workspace=workspace, role=WorkspaceRole.MEMBER)
    agent_memory = _memory(workspace=workspace, agent=agent, user=member.user)
    workspace_memory = _memory(
        workspace=workspace,
        agent=agent,
        user=member.user,
        scope="workspace",
        title="Workspace standard",
    )
    db_session.add_all([agent_memory, workspace_memory])
    await db_session.commit()

    updated = await db_async_client.patch(
        f"/api/v1/memories/{agent_memory.id}",
        headers=member.headers,
        json={"importance": 5},
    )
    deleted = await db_async_client.delete(
        f"/api/v1/memories/{workspace_memory.id}",
        headers=member.headers,
    )

    assert updated.status_code == 200
    assert updated.json()["importance"] == 5
    assert deleted.status_code == 403


async def test_manager_archive_and_purge_are_audited(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    workspace, agent = await _workspace_with_agent(db_session)
    manager = await _actor(db_session, workspace=workspace, role=WorkspaceRole.ADMIN)
    archived_memory = _memory(
        workspace=workspace,
        agent=agent,
        user=manager.user,
        scope="workspace",
        title="Archive me",
    )
    purged_memory = _memory(
        workspace=workspace,
        agent=agent,
        user=manager.user,
        scope="workspace",
        title="Purge me",
    )
    db_session.add_all([archived_memory, purged_memory])
    await db_session.commit()

    archived = await db_async_client.delete(
        f"/api/v1/memories/{archived_memory.id}",
        headers=manager.headers,
    )
    purged = await db_async_client.delete(
        f"/api/v1/memories/{purged_memory.id}",
        headers=manager.headers,
        params={"purge": "true"},
    )

    assert archived.status_code == 204
    assert purged.status_code == 204
    await db_session.refresh(archived_memory)
    assert archived_memory.status == "archived"
    assert archived_memory.archive_reason == "user_deleted"
    purged_count = await db_session.scalar(
        select(func.count(AgentMemory.id)).where(AgentMemory.id == purged_memory.id)
    )
    assert purged_count == 0
    audit_count = await db_session.scalar(
        select(func.count(AuditEvent.id)).where(
            AuditEvent.workspace_id == workspace.id,
            AuditEvent.resource_type == "memory",
            AuditEvent.action == "delete",
        )
    )
    assert audit_count == 2


async def test_content_edit_supersedes_and_detail_returns_the_chain(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    monkeypatch,
) -> None:
    workspace, agent = await _workspace_with_agent(db_session)
    member = await _actor(db_session, workspace=workspace, role=WorkspaceRole.MEMBER)
    memory = _memory(workspace=workspace, agent=agent, user=member.user)
    db_session.add(memory)
    await db_session.commit()

    _disable_embeddings(monkeypatch)
    updated = await db_async_client.patch(
        f"/api/v1/memories/{memory.id}",
        headers=member.headers,
        json={"content_md": "The corrected durable detail."},
    )

    assert updated.status_code == 200
    new_id = updated.json()["id"]
    assert new_id != str(memory.id)
    detail = await db_async_client.get(
        f"/api/v1/memories/{memory.id}",
        headers=member.headers,
    )
    assert detail.status_code == 200
    assert [item["id"] for item in detail.json()["chain"]] == [str(memory.id), new_id]

    default_list = await db_async_client.get("/api/v1/memories/", headers=member.headers)
    superseded_list = await db_async_client.get(
        "/api/v1/memories/",
        headers=member.headers,
        params={"status": "superseded", "limit": 1, "offset": 0},
    )
    assert [item["id"] for item in default_list.json()["memories"]] == [new_id]
    assert superseded_list.json()["total"] == 1
    assert superseded_list.json()["limit"] == 1


async def test_purging_latest_version_archives_its_predecessor(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    monkeypatch,
) -> None:
    workspace, agent = await _workspace_with_agent(db_session)
    member = await _actor(db_session, workspace=workspace, role=WorkspaceRole.MEMBER)
    memory = _memory(workspace=workspace, agent=agent, user=member.user)
    db_session.add(memory)
    await db_session.commit()
    _disable_embeddings(monkeypatch)

    updated = await db_async_client.patch(
        f"/api/v1/memories/{memory.id}",
        headers=member.headers,
        json={"content_md": "The corrected durable detail."},
    )
    latest_id = updated.json()["id"]

    purged = await db_async_client.delete(
        f"/api/v1/memories/{latest_id}",
        headers=member.headers,
        params={"purge": "true"},
    )

    assert purged.status_code == 204
    await db_session.refresh(memory)
    assert memory.status == "archived"
    assert memory.superseded_by_id is None
    assert memory.archive_reason == "user_deleted"
    assert await db_session.get(AgentMemory, latest_id) is None


async def test_purging_middle_version_relinks_the_chain(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    monkeypatch,
) -> None:
    workspace, agent = await _workspace_with_agent(db_session)
    member = await _actor(db_session, workspace=workspace, role=WorkspaceRole.MEMBER)
    memory = _memory(workspace=workspace, agent=agent, user=member.user)
    db_session.add(memory)
    await db_session.commit()
    _disable_embeddings(monkeypatch)

    middle = await db_async_client.patch(
        f"/api/v1/memories/{memory.id}",
        headers=member.headers,
        json={"content_md": "The first correction."},
    )
    middle_id = middle.json()["id"]
    latest = await db_async_client.patch(
        f"/api/v1/memories/{middle_id}",
        headers=member.headers,
        json={"content_md": "The final correction."},
    )
    latest_id = latest.json()["id"]

    purged = await db_async_client.delete(
        f"/api/v1/memories/{middle_id}",
        headers=member.headers,
        params={"purge": "true"},
    )

    assert purged.status_code == 204
    await db_session.refresh(memory)
    assert str(memory.superseded_by_id) == latest_id
    detail = await db_async_client.get(
        f"/api/v1/memories/{memory.id}",
        headers=member.headers,
    )
    assert [item["id"] for item in detail.json()["chain"]] == [str(memory.id), latest_id]


async def _workspace_with_agent(db: AsyncSession) -> tuple[Workspace, Agent]:
    suffix = uuid4().hex
    creator = build_user(email=f"memory-creator-{suffix}@example.com")
    workspace = build_workspace(slug=f"memory-routes-{suffix[:10]}")
    db.add_all([creator, workspace])
    await db.flush()
    agent = Agent(
        name="Memory Agent",
        slug=f"memory-agent-{suffix[:10]}",
        instructions="Remember carefully.",
        workspace_id=workspace.id,
        created_by=creator.id,
    )
    db.add(agent)
    await db.flush()
    return workspace, agent


async def _actor(
    db: AsyncSession,
    *,
    workspace: Workspace,
    role: WorkspaceRole,
) -> RouteActor:
    suffix = uuid4().hex
    user = build_user(email=f"memory-actor-{suffix}@example.com")
    db.add(user)
    await db.flush()
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=role,
    )
    db.add(membership)
    await db.flush()
    user.default_workspace_id = workspace.id
    session = await session_manager.create_session(db, str(user.id))
    await db.commit()
    return RouteActor(
        user=user,
        headers={
            **bearer_headers(session["session_token"]),
            "X-Workspace": workspace.slug,
        },
    )


def _memory(
    *,
    workspace: Workspace,
    agent: Agent,
    user: User,
    scope: str = "agent",
    title: str = "Durable detail",
) -> AgentMemory:
    return AgentMemory(
        workspace_id=workspace.id,
        scope=scope,
        agent_id=agent.id if scope == "agent" else None,
        user_id=user.id if scope == "user" else None,
        kind="core",
        memory_type="fact",
        title=title,
        content_md="The original durable detail.",
        importance=3,
        confidence=0.8,
        status="active",
        source="interactive",
        created_by="agent",
        created_by_user_id=user.id,
    )


def _disable_embeddings(monkeypatch) -> None:
    async def no_embedding(*_args, **_kwargs):
        return None

    save_memory_module = import_module("services.memories.save_memory")
    monkeypatch.setattr(save_memory_module, "try_embed_memory", no_embedding)
