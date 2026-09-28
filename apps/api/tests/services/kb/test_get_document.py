"""Knowledge-base document read tests."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from services.kb import get_kb_document
from tests.factories import build_kb_document, build_user, build_workspace
from tests.services.kb.conftest import KBActors


@pytest.mark.parametrize("hidden_kind", ["workspace", "private"])
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
