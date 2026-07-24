# apps/api/services/kb/write_policy.py

"""Content and provenance policy for every knowledge-base document write."""

import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from core.settings import settings
from models.kb import KBDocument
from services.kb.domain import (
    KB_DOCUMENT_TITLE_MAX_CHARS,
    KB_SOURCE_UPLOAD,
    KB_SOURCE_URL,
)


@dataclass(frozen=True)
class KBProvenance:
    """Backend-minted origin metadata for one knowledge-base write."""

    actor_kind: Literal["user", "agent", "system"]
    user_id: UUID | None = None
    agent_id: UUID | None = None
    run_id: UUID | None = None
    source_type: str = "manual"
    origin_ref: str | None = None


_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("Slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    (
        "JSON Web Token",
        re.compile(r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    ),
)


async def lock_and_find_kb_duplicate(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    content_hash: str,
    is_private: bool,
    existing_id: UUID | None = None,
) -> KBDocument | None:
    """Serialize an exact-content scope, then return its live duplicate."""
    lock_material = f"{workspace_id}:{int(is_private)}:{content_hash}".encode()
    lock_key = int.from_bytes(sha256(lock_material).digest()[:8], "big", signed=True)
    await db.execute(select(func.pg_advisory_xact_lock(lock_key)))

    filters = [
        KBDocument.workspace_id == workspace_id,
        KBDocument.content_hash == content_hash,
        KBDocument.is_private == is_private,
        KBDocument.deleted.is_(False),
    ]
    if existing_id is not None:
        filters.append(KBDocument.id != existing_id)
    return await db.scalar(select(KBDocument).where(*filters))


def enforce_kb_write_policy(
    *,
    workspace_id: UUID,
    provenance: KBProvenance,
    title: str,
    content_md: str | None,
    is_private: bool,
    existing: KBDocument | None = None,
    duplicate: KBDocument | None = None,
) -> None:
    """Reject a knowledge-base write that violates shared content invariants."""
    _require_provenance(provenance)
    _require_workspace_scope(workspace_id, existing=existing)
    _require_private_scope(existing=existing, is_private=is_private)
    _reject_secrets(title=title, content_md=content_md)
    _require_bounded_content(title=title, content_md=content_md)
    if duplicate is not None and duplicate.id != getattr(existing, "id", None):
        raise ConflictError(
            "An identical knowledge document already exists in this privacy scope",
            conflicting_resource=str(duplicate.id),
            details={"document_id": str(duplicate.id)},
        )


def _require_provenance(provenance: KBProvenance) -> None:
    missing = (
        (provenance.actor_kind == "user" and provenance.user_id is None)
        or (
            provenance.actor_kind == "agent"
            and (provenance.agent_id is None or provenance.run_id is None)
        )
        or (
            provenance.source_type in {KB_SOURCE_URL, KB_SOURCE_UPLOAD}
            and not provenance.origin_ref
        )
    )
    if missing:
        raise AppValidationError("KB writes require provenance")


def _require_workspace_scope(
    workspace_id: UUID | None,
    *,
    existing: KBDocument | None,
) -> None:
    if workspace_id is None:
        raise AppValidationError("KB writes require a workspace", field="workspace_id")
    if existing is not None and existing.workspace_id != workspace_id:
        raise NotFoundError(
            "Knowledge-base document not found",
            resource_type="kb_document",
            resource_id=str(existing.id),
        )


def _require_private_scope(*, existing: KBDocument | None, is_private: bool) -> None:
    if existing is not None and existing.is_private and not is_private:
        raise AppValidationError(
            "Private knowledge documents cannot be made workspace-shared",
            field="is_private",
        )


def _reject_secrets(*, title: str, content_md: str | None) -> None:
    candidate = f"{title}\n{content_md or ''}"
    for secret_class, pattern in _SECRET_PATTERNS:
        if pattern.search(candidate):
            raise AppValidationError(
                f"Knowledge documents cannot contain a detected {secret_class}",
                field="content_md",
            )


def _require_bounded_content(*, title: str, content_md: str | None) -> None:
    if not title.strip():
        raise AppValidationError("Document title is required", field="title")
    if len(title) > KB_DOCUMENT_TITLE_MAX_CHARS:
        raise AppValidationError(
            f"Document title cannot exceed {KB_DOCUMENT_TITLE_MAX_CHARS} characters",
            field="title",
        )
    if content_md is None:
        return
    if not content_md.strip():
        raise AppValidationError("Document content is required", field="content_md")
    if len(content_md.encode("utf-8")) > settings.KB_MAX_DOCUMENT_BYTES:
        raise AppValidationError(
            "Document content exceeds the knowledge-base size limit",
            field="content_md",
        )


__all__ = [
    "KBProvenance",
    "enforce_kb_write_policy",
    "lock_and_find_kb_duplicate",
]
