"""Real-pipeline corpus fixtures for the Gate G4 retrieval harness."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from core.database import set_session_tenant_context
from models.kb import KBDocument
from models.user import User
from models.workspace import Workspace
from services.kb import create_kb_document
from services.kb.embed_chunks import embed_kb_chunks
from services.kb.ingest_document import ingest_kb_document
from tests.factories import build_user, build_workspace
from tests.support.database import make_async_test_database_url
from tests.support.embeddings import FakeEmbeddingProvider

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CORPUS_FILENAMES = (
    "vpn_setup.md",
    "onboarding_guide.md",
    "travel_expense_policy.md",
    "api_error_codes.md",
    "security_incident_runbook.md",
    "pricing_policy.md",
    "product_roadmap.md",
    "meeting_notes_2026_06.md",
    "prompt_injection_basic.md",
    "prompt_injection_tool_call.md",
    "prompt_injection_exfil.md",
)
INJECTION_FILENAMES = (
    "prompt_injection_basic.md",
    "prompt_injection_tool_call.md",
    "prompt_injection_exfil.md",
)


@dataclass(frozen=True)
class RetrievalCorpus:
    """Persisted corpus actors and documents for one evaluation module."""

    db: AsyncSession
    workspace: Workspace
    creator: User
    other_user: User
    documents: dict[str, KBDocument]
    pending_document: KBDocument
    private_document: KBDocument
    isolation_workspace: Workspace
    isolation_user: User
    isolation_document: KBDocument

    @property
    def document_ids(self) -> set:
        """Return all primary-workspace corpus document ids."""
        return {
            *(document.id for document in self.documents.values()),
            self.pending_document.id,
            self.private_document.id,
        }


def _expanded_roadmap(seed: str, *, sections: int, marker: str) -> str:
    """Build a realistic long markdown source while keeping the checked-in seed readable."""
    detail = (
        f"{marker} records the owner, dependency, acceptance evidence, rollout boundary, "
        "security review, operator impact, recovery path, and measurable customer outcome. "
    ) * 16
    return "\n\n".join(
        (
            seed.strip(),
            *(
                f"## Release {index:02d}\n\n{detail}Release identifier {index:02d}."
                for index in range(1, sections + 1)
            ),
        )
    )


async def _seed_document(
    db: AsyncSession,
    *,
    workspace: Workspace,
    creator: User,
    title: str,
    content: str,
    is_private: bool = False,
    embed: bool = True,
) -> KBDocument:
    document = await create_kb_document(
        db,
        workspace_id=workspace.id,
        source_type="manual",
        title=title,
        created_by_user_id=creator.id,
        content=content,
        is_private=is_private,
        annotate=False,
    )
    await ingest_kb_document(
        db,
        document_id=document.id,
        workspace_id=workspace.id,
        initiated_by_user_id=creator.id,
    )
    if embed:
        await embed_kb_chunks(
            db,
            document_id=document.id,
            workspace_id=workspace.id,
            provider=FakeEmbeddingProvider(),
        )
    await db.refresh(document)
    return document


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def retrieval_corpus(
    migrated_test_database: str,
) -> AsyncIterator[RetrievalCorpus]:
    """Seed one isolated module corpus through create, ingest, and embed services."""
    engine = create_async_engine(
        make_async_test_database_url(migrated_test_database),
        poolclass=NullPool,
    )
    async with engine.connect() as connection:
        outer_transaction = await connection.begin()
        session_factory = async_sessionmaker(
            bind=connection,
            class_=AsyncSession,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        async with session_factory() as db:
            suffix = uuid4().hex
            creator = build_user(email=f"retrieval-creator-{suffix}@example.com")
            other_user = build_user(email=f"retrieval-other-{suffix}@example.com")
            workspace = build_workspace(slug=f"retrieval-{suffix[:12]}")
            isolation_user = build_user(email=f"retrieval-isolation-{suffix}@example.com")
            isolation_workspace = build_workspace(slug=f"retrieval-isolated-{suffix[:10]}")
            db.add_all(
                [
                    creator,
                    other_user,
                    workspace,
                    isolation_user,
                    isolation_workspace,
                ]
            )
            await db.flush()
            await set_session_tenant_context(
                db,
                workspace_id=workspace.id,
                user_id=creator.id,
            )

            documents: dict[str, KBDocument] = {}
            for filename in CORPUS_FILENAMES:
                content = (FIXTURES_DIR / filename).read_text(encoding="utf-8")
                if filename == "product_roadmap.md":
                    content = _expanded_roadmap(
                        content,
                        sections=24,
                        marker="Product roadmap sequencing",
                    )
                documents[filename] = await _seed_document(
                    db,
                    workspace=workspace,
                    creator=creator,
                    title=filename.removesuffix(".md").replace("_", " ").title(),
                    content=content,
                )

            pending_document = await _seed_document(
                db,
                workspace=workspace,
                creator=creator,
                title="Pending embedding capacity corpus",
                content=_expanded_roadmap(
                    "# Pending embedding capacity corpus",
                    sections=56,
                    marker="Pending capacity marker",
                ),
                embed=False,
            )
            private_document = await _seed_document(
                db,
                workspace=workspace,
                creator=creator,
                title="Creator private notes",
                content=(
                    "# Private notes\n\n"
                    "PRIVATE-CREATOR-CODE contains the creator's confidential launch notes."
                ),
                is_private=True,
            )
            await set_session_tenant_context(
                db,
                workspace_id=isolation_workspace.id,
                user_id=isolation_user.id,
            )
            isolation_document = await _seed_document(
                db,
                workspace=isolation_workspace,
                creator=isolation_user,
                title="Isolated workspace beacon",
                content=(
                    "# Isolation\n\nISOLATED-WORKSPACE-BEACON belongs only to the second workspace."
                ),
            )
            await set_session_tenant_context(
                db,
                workspace_id=workspace.id,
                user_id=creator.id,
            )

            assert documents["product_roadmap.md"].chunk_count > 20
            assert pending_document.chunk_count > 50

            try:
                yield RetrievalCorpus(
                    db=db,
                    workspace=workspace,
                    creator=creator,
                    other_user=other_user,
                    documents=documents,
                    pending_document=pending_document,
                    private_document=private_document,
                    isolation_workspace=isolation_workspace,
                    isolation_user=isolation_user,
                    isolation_document=isolation_document,
                )
            finally:
                await db.close()

        if outer_transaction.is_active:
            await outer_transaction.rollback()
    await engine.dispose()
