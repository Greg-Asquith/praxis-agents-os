// apps/web/src/features/workspaces/format.ts

import { titleCaseToken } from "@/lib/format"

const WORKSPACE_STATUS_LABELS: Record<string, string> = {
  active: "Active",
  archived: "Archived",
}

export function workspaceStatusLabel(status: string) {
  return WORKSPACE_STATUS_LABELS[status] ?? titleCaseToken(status, "Unknown")
}
