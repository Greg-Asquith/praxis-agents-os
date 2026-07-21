import { describe, expect, it } from "vitest"

import {
  connectionResourcesAreEditable,
  enabledSelectableResourceIds,
  integrationResourceIsSelectable,
} from "@/features/integrations/components/resource-selection-model"
import type { IntegrationResource } from "@/features/integrations/types"

function resource(overrides: Partial<IntegrationResource> = {}): IntegrationResource {
  return {
    availability: "available",
    connection_id: "connection-1",
    display_name: "Resource",
    enabled: true,
    external_id: "external-1",
    first_seen_at: "2026-07-21T12:00:00Z",
    id: "resource-1",
    last_seen_at: "2026-07-21T12:00:00Z",
    metadata: {},
    parent_external_id: null,
    removed_at: null,
    resource_type: "test_resource",
    writable: true,
    ...overrides,
  }
}

describe("resource selection model", () => {
  it("excludes removed enabled resources from the replace-set", () => {
    const removed = resource({
      availability: "removed",
      id: "removed-resource",
      removed_at: "2026-07-21T13:00:00Z",
    })

    expect(integrationResourceIsSelectable(removed)).toBe(false)
    expect(enabledSelectableResourceIds([resource(), removed])).toEqual(["resource-1"])
  })

  it("excludes Google Ads manager accounts from the replace-set", () => {
    const manager = resource({ id: "manager", metadata: { manager: true } })

    expect(integrationResourceIsSelectable(manager)).toBe(false)
    expect(enabledSelectableResourceIds([manager])).toEqual([])
  })

  it("keeps revoked connection resources read-only", () => {
    expect(connectionResourcesAreEditable(true, "active")).toBe(true)
    expect(connectionResourcesAreEditable(true, "revoked")).toBe(false)
    expect(connectionResourcesAreEditable(false, "active")).toBe(false)
  })
})
