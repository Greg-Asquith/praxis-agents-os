// apps/web/src/features/knowledge/components/source-sync-badge.tsx

import { Badge } from "@/components/ui/badge"
import { sourceSyncPresentation } from "@/features/knowledge/components/source-sync-status"
import type { KbSourceSyncStatus } from "@/features/knowledge/types"

export function SourceSyncBadge({ status }: { status: KbSourceSyncStatus }) {
  const presentation = sourceSyncPresentation(status)
  return <Badge variant={presentation.variant}>{presentation.label}</Badge>
}
