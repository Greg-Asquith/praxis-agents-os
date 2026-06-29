# apps/api/tests/factories/workspaces.py
"""Workspace model factories for tests."""

from uuid import UUID, uuid4

from models.workspace import Workspace, WorkspaceMembership, WorkspaceRole


def build_workspace(
    *,
    workspace_id: UUID | None = None,
    slug: str = "test-workspace",
    name: str = "Test Workspace",
    is_personal: bool = False,
) -> Workspace:
    """Build an unsaved workspace model for service tests."""
    return Workspace(
        id=workspace_id or uuid4(),
        slug=slug,
        name=name,
        is_personal=is_personal,
    )


def build_workspace_membership(
    *,
    membership_id: UUID | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
    role: WorkspaceRole = WorkspaceRole.MEMBER,
) -> WorkspaceMembership:
    """Build an unsaved workspace membership model for service tests."""
    return WorkspaceMembership(
        id=membership_id or uuid4(),
        workspace_id=workspace_id or uuid4(),
        user_id=user_id or uuid4(),
        role=role.value,
    )
