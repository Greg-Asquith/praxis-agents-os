# apps/api/tests/factories/kb.py

"""Knowledge-base model factories for tests."""

from uuid import UUID, uuid4

from models.kb import KBChunk, KBDocument
from models.workspace import Workspace


def build_kb_document(
    *,
    workspace: Workspace,
    document_id: UUID | None = None,
    **overrides,
) -> KBDocument:
    """Build an unsaved knowledge-base document."""
    defaults = {
        "id": document_id or uuid4(),
        "workspace_id": workspace.id,
        "title": "Test knowledge",
        "source_type": "manual",
        "status": "pending",
        "content_hash": "",
        "content_md": "# Test\n\nKnowledge content.",
        "annotation_enabled": False,
        "chunk_count": 0,
        "meta": {},
    }
    defaults.update(overrides)
    return KBDocument(**defaults)


def build_kb_chunk(
    *,
    document: KBDocument,
    chunk_id: UUID | None = None,
    chunk_index: int = 0,
    content: str = "Knowledge content.",
    **overrides,
) -> KBChunk:
    """Build an unsaved exact-substring chunk."""
    defaults = {
        "id": chunk_id or uuid4(),
        "document_id": document.id,
        "workspace_id": document.workspace_id,
        "chunk_index": chunk_index,
        "content": content,
        "char_start": 0,
        "char_end": len(content),
        "token_estimate": len(content) // 4,
        "meta": {"headings": []},
    }
    defaults.update(overrides)
    return KBChunk(**defaults)
