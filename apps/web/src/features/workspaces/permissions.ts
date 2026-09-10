import type { WorkspaceRole } from "./types"

export function canEditWorkspace(role: WorkspaceRole | null) {
  return role === "owner" || role === "admin" || role === "member"
}
