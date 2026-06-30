// apps/web/src/features/workspaces/components/workspace-role-badge.tsx

import { Badge } from "@/components/ui/badge"
import type { WorkspaceRole } from "@/features/workspaces/types"

const ROLE_LABELS: Record<WorkspaceRole, string> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
  read_only: "Read only",
}

function formatWorkspaceRole(role: WorkspaceRole | null) {
  return role ? ROLE_LABELS[role] : "No role"
}

export function WorkspaceRoleBadge({ role }: { role: WorkspaceRole | null }) {
  return (
    <Badge variant={role === "owner" ? "default" : "secondary"}>{formatWorkspaceRole(role)}</Badge>
  )
}
