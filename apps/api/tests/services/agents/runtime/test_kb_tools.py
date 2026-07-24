# apps/api/tests/services/agents/runtime/test_kb_tools.py

"""Knowledge-base runtime tool contract and trust-boundary tests."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from services.agents.runtime.tools.contract import TOOL_EFFECT_READ, TOOL_POLICY_AUTO
from services.agents.runtime.tools.kb import (
    KB_AGENT_SEARCH_DEFAULT_LIMIT,
    KnowledgeSearchFilters,
    ReadDocumentOutput,
    ReadRange,
    SearchKnowledgeOutput,
    read_document,
    search_knowledge,
)
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.embeddings.domain import EmbeddingProviderError
from services.kb.create_document import create_kb_document
from services.kb.domain import KB_SOURCE_MANUAL, KB_SOURCE_UPLOAD, KB_SOURCE_URL
from services.kb.ingest_document import ingest_kb_document
from services.kb.schemas import KBDocumentRead, KBSearchHit, KBSearchResult
from tests.factories import build_user, build_workspace
from tests.support.embeddings import FakeEmbeddingProvider

INJECTION_FIXTURE_TEXT = (
    Path(__file__).resolve().parents[3]
    / "integration"
    / "retrieval_eval"
    / "fixtures"
    / "prompt_injection_tool_call.md"
).read_text(encoding="utf-8")


class FailingEmbeddingProvider(FakeEmbeddingProvider):
    """Force the real search service through its lexical fallback."""

    async def embed_texts(self, texts, *, model, dimensions):
        raise EmbeddingProviderError("offline")


def _context(*, db: object, workspace: object, user: object):
    return SimpleNamespace(deps=SimpleNamespace(db=db, workspace=workspace, user=user))


async def test_search_knowledge_clamps_limit_and_preserves_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = SimpleNamespace(id=uuid4())
    user = SimpleNamespace(id=uuid4())
    document_id = uuid4()
    chunk_id = uuid4()
    captured: dict[str, object] = {}

    async def fake_search(_db, **kwargs):
        captured.update(kwargs)
        return KBSearchResult(
            query="policy",
            mode="lexical_fallback",
            results=[
                KBSearchHit(
                    id=chunk_id,
                    document_id=document_id,
                    chunk_index=2,
                    content="Quarterly reviews are required.",
                    context_line=None,
                    char_start=10,
                    char_end=43,
                    meta={},
                    pending_embedding=True,
                    title="Access policy",
                    source_type=KB_SOURCE_MANUAL,
                    external_url=None,
                    is_private=False,
                    score=0.5,
                    sources=["lexical"],
                )
            ],
        )

    monkeypatch.setattr("services.agents.runtime.tools.kb.search_chunks", fake_search)
    output = await search_knowledge(
        _context(db=object(), workspace=workspace, user=user),
        "  policy  ",
        filters=KnowledgeSearchFilters(
            source_types=[KB_SOURCE_MANUAL],
            private_only=True,
            document_ids=[document_id],
        ),
        limit=settings.KB_SEARCH_TOP_K_MAX + 20,
    )

    assert captured == {
        "workspace_id": workspace.id,
        "user_id": user.id,
        "query": "policy",
        "top_k": settings.KB_SEARCH_TOP_K_MAX,
        "source_types": [KB_SOURCE_MANUAL],
        "document_ids": [document_id],
        "private_only": True,
    }
    assert output["used_lexical_fallback"] is True
    assert output["results"][0] == {
        "document_id": str(document_id),
        "document_title": "Access policy",
        "source_type": KB_SOURCE_MANUAL,
        "is_private": False,
        "content": "Quarterly reviews are required.",
    }
    assert "read_document" in output["next_step"]
    SearchKnowledgeOutput.model_validate(output)


async def test_search_knowledge_defaults_to_a_small_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_search(_db, **kwargs):
        captured.update(kwargs)
        return KBSearchResult(query="policy", mode="hybrid", results=[])

    monkeypatch.setattr("services.agents.runtime.tools.kb.search_chunks", fake_search)
    context = _context(
        db=object(),
        workspace=SimpleNamespace(id=uuid4()),
        user=SimpleNamespace(id=uuid4()),
    )
    output = await search_knowledge(context, "policy")

    assert captured["top_k"] == KB_AGENT_SEARCH_DEFAULT_LIMIT
    assert "No matches" in output["next_step"]
    with pytest.raises(ModelRetry, match="at least 1"):
        await search_knowledge(context, "policy", limit=0)


async def test_read_document_caps_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = SimpleNamespace(id=uuid4())
    user = SimpleNamespace(id=uuid4())
    document_id = uuid4()
    content = "0123456789" * 10
    now = datetime.now(UTC)

    async def fake_read(_db, **kwargs):
        assert kwargs["workspace_id"] == workspace.id
        assert kwargs["user_id"] == user.id
        return KBDocumentRead(
            id=document_id,
            title="External policy",
            concept_id=None,
            source_type=KB_SOURCE_URL,
            source_updated_at=None,
            status="ready",
            processing_error=None,
            summary=None,
            external_url="https://example.com/policy",
            is_private=False,
            chunk_count=1,
            content_md=content,
            meta={},
            created_at=now,
            updated_at=now,
        )

    monkeypatch.setattr(
        "services.agents.runtime.tools.kb.get_kb_document",
        fake_read,
    )
    monkeypatch.setattr(settings, "KB_READ_DOCUMENT_MAX_CHARS", 12)

    output = await read_document(
        _context(db=object(), workspace=workspace, user=user),
        document_id,
        range=ReadRange(start=5, end=80),
    )
    validated = ReadDocumentOutput.model_validate(output)

    assert validated.start == 5
    assert validated.end == 17
    assert validated.content == content[5:17]


async def test_read_document_retries_for_invalid_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid4()
    now = datetime.now(UTC)
    monkeypatch.setattr(
        "services.agents.runtime.tools.kb.get_kb_document",
        lambda *_args, **_kwargs: None,
    )

    async def fake_read(_db, **_kwargs):
        return KBDocumentRead(
            id=document_id,
            title="Manual note",
            concept_id=None,
            source_type=KB_SOURCE_MANUAL,
            source_updated_at=None,
            status="ready",
            processing_error=None,
            summary=None,
            external_url=None,
            is_private=False,
            chunk_count=1,
            content_md="short",
            meta={},
            created_at=now,
            updated_at=now,
        )

    monkeypatch.setattr("services.agents.runtime.tools.kb.get_kb_document", fake_read)
    context = _context(
        db=object(),
        workspace=SimpleNamespace(id=uuid4()),
        user=SimpleNamespace(id=uuid4()),
    )

    with pytest.raises(ModelRetry, match="less than the document length"):
        await read_document(context, document_id, range=ReadRange(start=5))


async def test_real_kb_pipeline_returns_plain_content_and_respects_visibility(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = build_user(email=f"kb-tool-{uuid4().hex}@example.com")
    other_user = build_user(email=f"kb-tool-other-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"kb-tool-{uuid4().hex[:12]}")
    db_session.add_all([user, other_user, workspace])
    await db_session.flush()
    hostile = INJECTION_FIXTURE_TEXT

    async def seed(title: str, *, creator_id, is_private: bool = False):
        seeded_content = f"{hostile}\n\nFixture source: {title}\n"
        document = await create_kb_document(
            db_session,
            workspace_id=workspace.id,
            source_type=KB_SOURCE_MANUAL,
            title=title,
            created_by_user_id=creator_id,
            content=seeded_content,
            is_private=is_private,
            annotate=False,
        )
        await ingest_kb_document(
            db_session,
            document_id=document.id,
            workspace_id=workspace.id,
            initiated_by_user_id=creator_id,
        )
        await db_session.refresh(document)
        return document, seeded_content

    manual_document, manual_content = await seed("Manual fixture", creator_id=user.id)
    url_document, url_content_source = await seed("URL fixture", creator_id=user.id)
    upload_document, upload_content = await seed("Upload fixture", creator_id=user.id)
    hidden_document, _hidden_content = await seed(
        "Other user's private fixture",
        creator_id=other_user.id,
        is_private=True,
    )
    url_document.source_type = KB_SOURCE_URL
    url_document.external_url = "https://example.com/hostile"
    upload_document.source_type = KB_SOURCE_UPLOAD
    await db_session.flush()

    async def lexical_search(db, **kwargs):
        from services.kb.search_chunks import search_chunks as real_search

        return await real_search(db, provider=FailingEmbeddingProvider(), **kwargs)

    monkeypatch.setattr("services.agents.runtime.tools.kb.search_chunks", lexical_search)
    context = _context(db=db_session, workspace=workspace, user=user)
    search_output = await search_knowledge(context, "delete_all_files", limit=10)
    results_by_document = {result["document_id"]: result for result in search_output["results"]}

    assert '{"tool": "delete_all_files"' in results_by_document[str(manual_document.id)]["content"]
    assert '{"tool": "delete_all_files"' in results_by_document[str(upload_document.id)]["content"]
    assert '{"tool": "delete_all_files"' in results_by_document[str(url_document.id)]["content"]
    assert str(hidden_document.id) not in results_by_document
    assert all(isinstance(result["content"], str) for result in search_output["results"])

    manual_read = await read_document(context, manual_document.id)
    url_read = await read_document(context, url_document.id)
    upload_read = await read_document(context, upload_document.id)
    assert manual_read["content"] == manual_content
    assert upload_read["content"] == upload_content
    assert url_read["content"] == url_content_source
    with pytest.raises(ModelRetry, match="not found"):
        await read_document(context, hidden_document.id)


def test_kb_catalog_entries_are_bounded_read_tools_with_presentations() -> None:
    for name in ("search_knowledge", "read_document"):
        definition = RUNTIME_TOOL_CATALOG[name]
        assert definition.provider == "kb"
        assert definition.effect == TOOL_EFFECT_READ
        assert definition.default_policy == TOOL_POLICY_AUTO
        assert definition.configurable is False
        assert definition.auto_mount is True
        assert definition.presentation.icon in {"search", "book"}
        assert definition.presentation.running_label
        assert definition.presentation.completed_label
        assert definition.presentation.failed_label
