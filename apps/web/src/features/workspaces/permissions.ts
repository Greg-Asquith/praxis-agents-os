import type { Workspace, WorkspaceRole } from "./types"

export function canEditWorkspace(role: WorkspaceRole | null) {
  return role === "owner" || role === "admin" || role === "member"
}

export function canRemoveWorkspaceMembers(workspace: Workspace, isSuperAdmin: boolean) {
  return (
    !workspace.is_personal &&
    workspace.current_user_role !== null &&
    (isSuperAdmin ||
      workspace.current_user_role === "owner" ||
      workspace.current_user_role === "admin")
  )
}
