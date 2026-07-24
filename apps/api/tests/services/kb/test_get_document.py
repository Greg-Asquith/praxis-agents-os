"""Knowledge-base document read tests."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from services.kb import get_kb_document
from tests.factories import build_kb_document, build_user, build_workspace
from tests.services.kb.conftest import KBActors


async def test_get_document_returns_canonical_content(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    document = build_kb_document(
        workspace=kb_actors.workspace,
        created_by_user_id=kb_actors.user.id,
        status="ready",
        source_updated_at=datetime.now(UTC),
        is_private=True,
        chunk_count=2,
    )
    db_session.add(document)
    await db_session.flush()

    result = await get_kb_document(
        db_session,
        workspace_id=kb_actors.workspace.id,
        user_id=kb_actors.user.id,
        document_id=document.id,
    )

    assert result.id == document.id
    assert result.content_md == document.content_md
    assert result.is_private is True
    assert result.chunk_count == 2


@pytest.mark.parametrize("hidden_kind", ["workspace", "private", "deleted"])
async def test_get_document_hides_all_invisible_documents_as_not_found(
    db_session: AsyncSession,
    kb_actors: KBActors,
    hidden_kind: str,
) -> None:
    other_user = build_user(email=f"kb-other-{uuid4().hex}@example.com")
    other_workspace = build_workspace(slug=f"kb-other-{uuid4().hex[:12]}")
    db_session.add_all([other_user, other_workspace])
    await db_session.flush()
    document = build_kb_document(
        workspace=other_workspace if hidden_kind == "workspace" else kb_actors.workspace,
        created_by_user_id=other_user.id if hidden_kind == "private" else kb_actors.user.id,
        is_private=hidden_kind == "private",
        deleted_at=datetime.now(UTC) if hidden_kind == "deleted" else None,
    )
    db_session.add(document)
    await db_session.flush()

    with pytest.raises(NotFoundError):
        await get_kb_document(
            db_session,
            workspace_id=kb_actors.workspace.id,
            user_id=kb_actors.user.id,
            document_id=document.id,
        )
