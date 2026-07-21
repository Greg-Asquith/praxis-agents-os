import { describe, expect, it } from "vitest"

import {
  discoveryFinished,
  discoveryStatusLabel,
} from "@/features/integrations/components/resource-discovery"

describe("resource discovery", () => {
  it("detects the transition that requires a final resource refresh", () => {
    expect(discoveryFinished("discovery_pending", "active")).toBe(true)
    expect(discoveryFinished("discovery_pending", "error")).toBe(true)
    expect(discoveryFinished("active", "active")).toBe(false)
  })

  it("renders the persisted discovery states in operator language", () => {
    expect(discoveryStatusLabel("running")).toBe("Discovery in progress")
    expect(discoveryStatusLabel("succeeded")).toBe("Discovery completed")
    expect(discoveryStatusLabel("failed")).toBe("Discovery failed")
  })
})
