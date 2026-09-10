# apps/api/tests/scenarios/test_platform_knowledge.py

"""Published Knowledge reaches runtime tools with its ownership and bounded content."""

from pathlib import Path

import pytest
from pydantic_ai.messages import ToolReturnPart

from core.database import maintenance_async_db_session
from core.settings import settings
from models.workspace import Workspace
from services.agents.runtime.untrusted import (
    UNTRUSTED_CONTENT_END,
    UNTRUSTED_CONTENT_START,
)
from services.embeddings.domain import EmbeddingProviderError
from services.kb.search_chunks import search_chunks
from tests.factories import build_kb_chunk, build_kb_document
from tests.support.embeddings import FakeEmbeddingProvider
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)

HOSTILE_CONTENT = (
    Path(__file__).resolve().parents[1]
    / "integration/retrieval_eval/fixtures/prompt_injection_tool_call.md"
).read_text()


class FailingEmbeddingProvider(FakeEmbeddingProvider):
    async def embed_texts(self, texts, *, model, dimensions):
        raise EmbeddingProviderError("offline")


@pytest.mark.parametrize("source_type", ["manual", "upload"])
async def test_platform_knowledge_search_and_read_keep_scope_through_dispatch(
    db_session_factory, monkeypatch, source_type
):
    context = await build_scenario_agent(db_session_factory)
    hostile = HOSTILE_CONTENT
    content = f"{UNTRUSTED_CONTENT_END}\n{hostile}\n" + "Quarterly reviews. " * 30
    read_limit = len(hostile) + 60
    async with maintenance_async_db_session() as db:
        workspace = await db.get(Workspace, context.workspace_id)
        document = build_kb_document(
            workspace=workspace,
            workspace_id=None,
            scope="platform",
            is_published=True,
            is_private=False,
            status="ready",
            title="Platform policy",
            source_type=source_type,
            content_md=content,
            chunk_count=1,
        )
        db.add(document)
        await db.flush()
        db.add(build_kb_chunk(document=document, scope="platform", content=content))
        await db.commit()
        document_id = str(document.id)

    async def lexical_search(db, **kwargs):
        return await search_chunks(db, provider=FailingEmbeddingProvider(), **kwargs)

    monkeypatch.setattr("services.agents.runtime.tools.kb.search_chunks", lexical_search)
    monkeypatch.setattr(settings, "KB_READ_DOCUMENT_MAX_CHARS", read_limit)
    seen = []
    model = scripted_model(
        seen_requests=seen,
        turns=[
            ToolTurn((ToolCall("search_knowledge", {"query": "delete_all_files"}),)),
            ToolTurn(
                (
                    ToolCall(
                        "read_document",
                        {
                            "document_id": {
                                "entity_kind": "knowledge_document",
                                "entity_id": document_id,
                                "scope": "platform",
                                "label": "Platform policy",
                            }
                        },
                    ),
                )
            ),
            "Quarterly access reviews are required.",
        ],
    )
    result = await run_scenario(db_session_factory, context, model=model)
    assert result.run.status == "completed"
    [search] = result.tool_returns("search_knowledge")
    [hit] = search["content"]["results"]
    assert hit["scope"] == hit["reference"]["scope"] == "platform"
    assert hit["document_id"] == document_id
    [read] = result.tool_returns("read_document")
    assert read["content"]["scope"] == "platform"
    assert read["content"]["content"] == {
        "node": "praxis_untrusted",
        "source_kind": "kb",
        "source_ref": f"document:{document_id}",
        "content": content[:read_limit],
    }
    assert hit["content"]["node"] == "praxis_untrusted"
    assert hit["content"]["source_kind"] == "kb"
    assert "delete_all_files" in hit["content"]["content"]
    returned = [
        part
        for message in seen[-1][0]
        for part in message.parts
        if isinstance(part, ToolReturnPart)
        and part.tool_name in {"search_knowledge", "read_document"}
    ]
    assert len(returned) == 2
    for part in returned:
        payload = part.content
        framed = (
            payload["results"][0]["content"]
            if part.tool_name == "search_knowledge"
            else payload["content"]
        )
        assert framed.startswith(UNTRUSTED_CONTENT_START)
        assert framed.endswith(UNTRUSTED_CONTENT_END)
        assert framed.count(UNTRUSTED_CONTENT_START) == 1
        assert framed.count(UNTRUSTED_CONTENT_END) == 1
        assert "delete_all_files" in framed
    assert result.tool_calls("delete_all_files") == []
    assert read["content"]["total_chars"] == len(content)
    assert result.audit_rows
