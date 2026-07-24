import { describe, expect, it } from "vitest"

import {
  discoveryFinished,
  discoveryIsInFlight,
  discoveryNeedsRecovery,
  discoveryStatusLabel,
} from "@/features/integrations/components/resource-discovery"
import type { IntegrationConnection } from "@/features/integrations/types"

function pendingConnection(discoveryInFlight: boolean): IntegrationConnection {
  return {
    connected_by_user_id: "user-1",
    created_at: "2026-07-24T10:00:00Z",
    credential: null,
    discovery_in_flight: discoveryInFlight,
    duplicate_of_connection_ids: [],
    id: "connection-1",
    label: "Inbox",
    latest_discovery_run: null,
    owner_scope: "user",
    owner_user_id: "user-1",
    owner_workspace_id: null,
    provider_key: "gmail",
    status: "discovery_pending",
    status_reason: "resource_discovery_queued",
    updated_at: "2026-07-24T10:00:00Z",
  }
}

describe("resource discovery", () => {
  it("detects the transition that requires a final resource refresh", () => {
    expect(discoveryFinished("discovery_pending", "active")).toBe(true)
    expect(discoveryFinished("discovery_pending", "error")).toBe(true)
    expect(discoveryFinished("active", "active")).toBe(false)
  })

  it("renders the persisted discovery states in operator language", () => {
    expect(discoveryStatusLabel("running")).toBe("Looking for resources…")
    expect(discoveryStatusLabel("succeeded")).toBe("Resources are up to date")
    expect(discoveryStatusLabel("failed")).toBe("Resources could not be checked")
  })

  it("distinguishes active work from a pending status without a job", () => {
    expect(discoveryIsInFlight(pendingConnection(true))).toBe(true)
    expect(discoveryNeedsRecovery(pendingConnection(true))).toBe(false)
    expect(discoveryIsInFlight(pendingConnection(false))).toBe(false)
    expect(discoveryNeedsRecovery(pendingConnection(false))).toBe(true)
  })
})
