"""Shared ownership contracts for Skills, Knowledge, Files, and Artifacts."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.user import User


class ContentScope(StrEnum):
    """Ownership boundary shared by all four content types."""

    WORKSPACE = "workspace"
    PLATFORM = "platform"


def can_manage_platform_content(*, scope: str, deleted: bool, actor: User | None) -> bool:
    """Checks platform management authority independently of workspace roles."""
    from core.dependencies import is_super_admin_email

    return (
        scope == ContentScope.PLATFORM
        and not deleted
        and actor is not None
        and is_super_admin_email(actor.email)
    )
