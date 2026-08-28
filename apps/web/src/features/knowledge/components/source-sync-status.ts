// apps/web/src/features/knowledge/components/source-sync-status.ts

import type { KbSourceSyncStatus } from "@/features/knowledge/types"

const PRESENTATIONS = {
  pending: { label: "Sync pending", variant: "secondary" },
  ready: { label: "Synced", variant: "success" },
  error: { label: "Refresh failed", variant: "destructive" },
  unavailable: { label: "Page unavailable", variant: "warning" },
  disconnected: { label: "Connection unavailable", variant: "outline" },
} satisfies Record<
  KbSourceSyncStatus,
  { label: string; variant: "destructive" | "outline" | "secondary" | "success" | "warning" }
>

export function sourceSyncPresentation(status: KbSourceSyncStatus) {
  return PRESENTATIONS[status]
}
