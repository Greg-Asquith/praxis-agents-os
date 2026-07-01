// apps/web/src/features/conversations/components/run-status-badge.tsx

import { Badge } from "@/components/ui/badge"
import { runStatusLabel } from "@/features/conversations/format"
import type { AgentRunStatus } from "@/features/conversations/types"

export function RunStatusBadge({ status }: { status: AgentRunStatus }) {
  if (status === "failed" || status === "cancelled") {
    return <Badge variant="destructive">{runStatusLabel(status)}</Badge>
  }

  if (status === "awaiting_approval") {
    return <Badge variant="secondary">{runStatusLabel(status)}</Badge>
  }

  return <Badge>{runStatusLabel(status)}</Badge>
}
