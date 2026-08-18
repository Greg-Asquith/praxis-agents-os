# apps/api/services/files/folder_utils.py

"""Helpers shared by human and agent folder operations."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.files import FileFolder
from services.files.utils import normalize_required_text

FOLDER_NAME_UNIQUE_INDEX = "uq_file_folders_workspace_name_live"
FOLDER_CONVERSATION_UNIQUE_INDEX = "uq_file_folders_workspace_conversation_live"
FOLDER_NAME_RETRY_LIMIT = 10


def is_folder_integrity_error(exc: IntegrityError, *, allowed: set[str]) -> bool:
    """Return whether Postgres attributed an integrity error to an allowed folder index."""
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None)
    if constraint_name in allowed:
        return True
    return any(name in str(exc) for name in allowed)


async def folder_by_name(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    name: str,
) -> FileFolder | None:
    normalized = normalize_required_text(name)
    return await db.scalar(
        select(FileFolder).where(
            FileFolder.workspace_id == workspace_id,
            FileFolder.deleted.is_(False),
            func.lower(FileFolder.name) == normalized.lower(),
        )
    )


async def available_folder_name(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    requested_name: str,
) -> str:
    """Choose a case-insensitively unique live folder name with a numeric suffix."""
    base = normalize_required_text(requested_name)
    existing = set(
        await db.scalars(
            select(func.lower(FileFolder.name)).where(
                FileFolder.workspace_id == workspace_id,
                FileFolder.deleted.is_(False),
            )
        )
    )
    if base.lower() not in existing:
        return base
    suffix_number = 2
    while True:
        suffix = f" ({suffix_number})"
        candidate = f"{base[: 255 - len(suffix)]}{suffix}"
        if candidate.lower() not in existing:
            return candidate
        suffix_number += 1
