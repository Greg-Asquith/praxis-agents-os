"""Retrieval preserves hostile fixture text as inert, byte-faithful data."""

import pytest

from services.kb import search_chunks
from tests.integration.retrieval_eval.conftest import (
    INJECTION_FILENAMES,
    RetrievalCorpus,
)
from tests.support.embeddings import FakeEmbeddingProvider

pytestmark = pytest.mark.asyncio(loop_scope="module")

# Plan 046's framing tests consume these same fixture files; do not rename or
# "fix" their content.
_QUERY_BY_FILENAME = {
    "prompt_injection_basic.md": "INERT-BASIC-FIXTURE",
    "prompt_injection_tool_call.md": "INERT-TOOL-FIXTURE",
    "prompt_injection_exfil.md": "INERT-EXFIL-FIXTURE",
}


async def test_hostile_documents_round_trip_as_exact_source_spans(
    retrieval_corpus: RetrievalCorpus,
) -> None:
    returned_text: dict[str, str] = {}

    for filename in INJECTION_FILENAMES:
        document = retrieval_corpus.documents[filename]
        result = await search_chunks(
            retrieval_corpus.db,
            workspace_id=retrieval_corpus.workspace.id,
            user_id=retrieval_corpus.creator.id,
            query=_QUERY_BY_FILENAME[filename],
            provider=FakeEmbeddingProvider(),
        )
        hit = next(hit for hit in result.results if hit.document_id == document.id)
        assert document.content_md is not None
        assert hit.content == document.content_md[hit.char_start : hit.char_end]
        returned_text[filename] = hit.content

    assert '{"tool": "delete_all_files"' in returned_text["prompt_injection_tool_call.md"]
    assert "https://evil.example/leak?d=SYSTEM_PROMPT" in returned_text["prompt_injection_exfil.md"]
