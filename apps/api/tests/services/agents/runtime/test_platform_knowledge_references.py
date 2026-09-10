# apps/api/tests/services/agents/runtime/test_platform_knowledge_references.py

"""Knowledge pickers and resolution share publication and privacy boundaries."""

from types import SimpleNamespace

from core.database import maintenance_async_db_session
from services.agents.runtime.entity_references.domain import KnowledgeDocumentReference
from services.agents.runtime.entity_references.internal import _resolve_documents, _search_documents
from tests.factories import build_kb_document, build_user, build_workspace


async def test_platform_knowledge_picker_filters_before_pagination(db_session_factory):
    async with maintenance_async_db_session() as db:
        workspace = build_workspace(slug="knowledge-picker")
        other_workspace = build_workspace(slug="knowledge-other")
        actor = build_user(email="picker@example.com")
        other_actor = build_user(email="other-picker@example.com")
        db.add_all([workspace, other_workspace, actor, other_actor])
        await db.flush()
        local = build_kb_document(workspace=workspace, title="Policy local", is_private=False)
        platform = build_kb_document(
            workspace=workspace,
            title="Policy platform",
            scope="platform",
            workspace_id=None,
            is_published=True,
            is_private=False,
        )
        own_private = build_kb_document(
            workspace=workspace,
            title="Policy own",
            is_private=True,
            created_by_user_id=actor.id,
        )
        hidden = [
            build_kb_document(
                workspace=workspace,
                title="Policy draft",
                scope="platform",
                workspace_id=None,
                is_private=False,
            ),
            build_kb_document(
                workspace=workspace,
                title="Policy private",
                is_private=True,
                created_by_user_id=other_actor.id,
            ),
            build_kb_document(workspace=other_workspace, title="Policy other", is_private=False),
            build_kb_document(
                workspace=workspace,
                title="Policy unavailable",
                source_type="url",
                source_sync_status="unavailable",
                is_private=False,
            ),
        ]
        db.add_all([local, platform, own_private, *hidden])
        await db.flush()
        context = SimpleNamespace(db=db, workspace=workspace, actor=actor)
        choices = []
        cursor = None
        for _ in range(3):
            page = await _search_documents(context, "Policy", {}, 1, cursor)
            assert len(page.choices) == 1
            choices.extend(page.choices)
            cursor = page.next_cursor
        assert cursor is None
        assert {choice.value["entity_id"] for choice in choices} == {
            str(local.id),
            str(platform.id),
            str(own_private.id),
        }
        platform_choice = next(choice for choice in choices if choice.value["scope"] == "platform")
        assert platform_choice.description.startswith("Platform ·")
        all_ids = [local.id, platform.id, own_private.id, *(row.id for row in hidden)]
        resolved = await _resolve_documents(context, all_ids, {})
        assert {choice.identity for choice in resolved} == {choice.identity for choice in choices}
        platform.is_published = False
        await db.flush()
        assert await _resolve_documents(context, [platform.id], {}) == ()
        page = await _search_documents(context, "Policy platform", {}, 10, None)
        assert page.choices == ()


def test_historical_knowledge_reference_defaults_to_workspace():
    document = build_kb_document(workspace=build_workspace())
    reference = KnowledgeDocumentReference(entity_id=document.id, label="Policy")
    assert reference.scope == "workspace"
