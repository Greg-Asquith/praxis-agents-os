# apps/api/tests/routes/notifications/test_notification_routes.py

"""HTTP-boundary tests for the notification inbox."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from models.notification import Notification
from models.user import User
from models.workspace import Workspace, WorkspaceRole
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers

_BASE = "/api/v1/notifications"


@dataclass(frozen=True)
class RouteActor:
    user: User
    headers: dict[str, str]


async def test_recipient_reads_marks_and_archives_their_inbox(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    workspace = await _workspace(db_session)
    other_workspace = await _workspace(db_session)
    recipient = await _actor(db_session, workspace=workspace, role=WorkspaceRole.READ_ONLY)
    await _join(db_session, workspace=other_workspace, user=recipient.user)
    job_failed = _notification(recipient=recipient.user, workspace_id=workspace.id)
    personal = _notification(recipient=recipient.user, workspace_id=None)
    elsewhere = _notification(recipient=recipient.user, workspace_id=other_workspace.id)
    db_session.add_all([job_failed, personal, elsewhere])
    await db_session.commit()

    listed = await db_async_client.get(f"{_BASE}/", headers=recipient.headers)
    assert {item["id"] for item in listed.json()["items"]} == {
        str(job_failed.id),
        str(personal.id),
    }
    assert await _unread(db_async_client, recipient) == 2

    read = await db_async_client.post(f"{_BASE}/{job_failed.id}/read", headers=recipient.headers)
    assert read.json()["read_at"] is not None
    assert await _unread(db_async_client, recipient) == 1

    read_all = await db_async_client.post(f"{_BASE}/read-all", headers=recipient.headers)
    assert read_all.json() == {"updated": 1}
    assert await _unread(db_async_client, recipient) == 0

    archived = await db_async_client.post(
        f"{_BASE}/{job_failed.id}/archive", headers=recipient.headers
    )
    assert archived.status_code == 200
    listed = await db_async_client.get(f"{_BASE}/", headers=recipient.headers)
    assert [item["id"] for item in listed.json()["items"]] == [str(personal.id)]

    await db_session.refresh(elsewhere)
    assert elsewhere.read_at is None


async def test_no_one_else_can_list_read_or_act_on_a_notification(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    workspace = await _workspace(db_session)
    recipient = await _actor(db_session, workspace=workspace, role=WorkspaceRole.MEMBER)
    teammate = await _actor(db_session, workspace=workspace, role=WorkspaceRole.OWNER)
    outsider = await _actor(
        db_session, workspace=await _workspace(db_session), role=WorkspaceRole.OWNER
    )
    note = _notification(recipient=recipient.user, workspace_id=workspace.id)
    db_session.add(note)
    await db_session.commit()

    for actor in (teammate, outsider):
        listed = await db_async_client.get(f"{_BASE}/", headers=actor.headers)
        assert listed.json()["items"] == []
        assert await _unread(db_async_client, actor) == 0
        await db_async_client.post(f"{_BASE}/read-all", headers=actor.headers)
        for suffix in ("read", "unread", "archive", "actions/review"):
            response = await db_async_client.post(
                f"{_BASE}/{note.id}/{suffix}", headers=actor.headers
            )
            assert response.status_code in (403, 404), (suffix, response.status_code)

    await db_session.refresh(note)
    assert note.read_at is None
    assert note.archived is False
    assert note.recipient_user_id == recipient.user.id


async def _unread(client: AsyncClient, actor: RouteActor) -> int:
    response = await client.get(f"{_BASE}/unread-count", headers=actor.headers)
    assert response.status_code == 200
    return response.json()["unread"]


def _notification(*, recipient: User, workspace_id: UUID | None) -> Notification:
    return Notification(
        notification_type="job_failed",
        title="Background job failed",
        body="The file couldn't be read.",
        payload={},
        actions=[],
        recipient_user_id=recipient.id,
        workspace_id=workspace_id,
        source="jobs",
    )


async def _workspace(db: AsyncSession) -> Workspace:
    suffix = uuid4().hex[:12]
    workspace = build_workspace(slug=f"inbox-{suffix}", name=f"Inbox {suffix}")
    db.add(workspace)
    await db.flush()
    return workspace


async def _join(db: AsyncSession, *, workspace: Workspace, user: User) -> None:
    db.add(build_workspace_membership(workspace_id=workspace.id, user_id=user.id))
    await db.flush()


async def _actor(db: AsyncSession, *, workspace: Workspace, role: WorkspaceRole) -> RouteActor:
    user = build_user(email=f"inbox-{uuid4().hex}@example.com")
    db.add(user)
    await db.flush()
    db.add(build_workspace_membership(workspace_id=workspace.id, user_id=user.id, role=role))
    user.default_workspace_id = workspace.id
    session = await session_manager.create_session(db, str(user.id))
    await db.commit()
    return RouteActor(
        user=user,
        headers={**bearer_headers(session["session_token"]), "X-Workspace": workspace.slug},
    )
