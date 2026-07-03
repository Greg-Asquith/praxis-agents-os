# apps/api/tests/factories/skills.py
"""Skill model factories for tests."""

from uuid import uuid4

from models.skills import Skill
from models.user import User
from models.workspace import Workspace


def build_skill(
    *,
    workspace: Workspace,
    created_by: User,
    **overrides,
) -> Skill:
    """Build an unsaved skill model for service tests."""
    defaults = {
        "name": f"skill-{uuid4().hex[:8]}",
        "human_name": "Test Skill",
        "description": "Reusable operating guidance.",
        "instructions": "Follow the documented workflow.",
        "workspace_id": workspace.id,
        "created_by": created_by.id,
    }
    defaults.update(overrides)
    return Skill(**defaults)
