# apps/api/tests/services/kb/conftest.py

"""Shared knowledge-base service fixtures."""

from dataclasses import dataclass
from uuid import uuid4

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace
from tests.factories import build_user, build_workspace


@dataclass(frozen=True)
class KBActors:
    workspace: Workspace
    user: User


@pytest_asyncio.fixture
async def kb_actors(db_session: AsyncSession) -> KBActors:
    """Persist one workspace and creating user."""
    suffix = uuid4().hex
    user = build_user(email=f"kb-{suffix}@example.com")
    workspace = build_workspace(slug=f"kb-{suffix[:12]}")
    db_session.add_all([user, workspace])
    await db_session.flush()
    return KBActors(workspace=workspace, user=user)
