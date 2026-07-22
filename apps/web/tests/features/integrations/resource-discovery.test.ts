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
    expect(discoveryStatusLabel("running")).toBe("Looking for resources…")
    expect(discoveryStatusLabel("succeeded")).toBe("Resources are up to date")
    expect(discoveryStatusLabel("failed")).toBe("Resources could not be checked")
  })
})
