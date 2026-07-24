// apps/web/src/features/knowledge/components/document-status-badge.tsx

import { Badge } from "@/components/ui/badge"
import { KB_STATUS_PRESENTATION } from "@/features/knowledge/status"
import type { KbProcessingStatus } from "@/features/knowledge/types"

export function DocumentStatusBadge({ status }: { status: KbProcessingStatus }) {
  const presentation = KB_STATUS_PRESENTATION[status]
  return <Badge variant={presentation.variant}>{presentation.label}</Badge>
}
