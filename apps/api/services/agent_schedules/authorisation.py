# apps/api/services/agent_schedules/authorisation.py

"""Authorisation helpers for agent schedule mutations."""

from core.exceptions.auth import AuthorizationError
from models.agent import AgentSchedule
from models.user import User
from models.workspace import WorkspaceMembership, WorkspaceRole

_WORKSPACE_ADMIN_ROLES = {WorkspaceRole.ADMIN.value, WorkspaceRole.OWNER.value}


def is_schedule_mutation_admin(membership: WorkspaceMembership) -> bool:
    """Return whether a workspace membership can mutate any schedule in the workspace."""

    return membership.role in _WORKSPACE_ADMIN_ROLES


def assert_can_create_schedule(*, membership: WorkspaceMembership) -> None:
    """Require a workspace membership that may create schedule-owned automation."""

    if membership.role == WorkspaceRole.READ_ONLY.value:
        raise AuthorizationError("Read-only members cannot create schedules")


def assert_can_mutate_schedule(
    *,
    schedule: AgentSchedule,
    current_user: User,
    membership: WorkspaceMembership,
) -> None:
    """Require schedule owner or workspace admin/owner access for schedule mutation."""

    if membership.role == WorkspaceRole.READ_ONLY.value:
        raise AuthorizationError("Read-only members cannot modify schedules")

    if schedule.user_id == current_user.id:
        return

    if is_schedule_mutation_admin(membership):
        return

    raise AuthorizationError("Requires schedule owner or workspace admin access")
