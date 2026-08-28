import { describe, expect, it } from "vitest"

import { sourceSyncPresentation } from "@/features/knowledge/components/source-sync-status"
import type { KbSourceSyncStatus } from "@/features/knowledge/types"

describe("Knowledge Base source sync badge", () => {
  it("presents every sync state in operator language", () => {
    const statuses: KbSourceSyncStatus[] = [
      "pending",
      "ready",
      "error",
      "unavailable",
      "disconnected",
    ]
    expect(statuses.map((status) => sourceSyncPresentation(status).label)).toEqual([
      "Sync pending",
      "Synced",
      "Refresh failed",
      "Page unavailable",
      "Connection unavailable",
    ])
  })
})
