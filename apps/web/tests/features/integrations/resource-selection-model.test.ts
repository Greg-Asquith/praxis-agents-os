// apps/web/tests/features/integrations/resource-selection-model.test.ts

import { describe, expect, it } from "vitest"

import {
  connectionResourcesAreEditable,
  enabledSelectableResourceIds,
  integrationResourceIsSelectable,
  resourcesInHierarchyOrder,
  resourcesWithExpandedParents,
} from "@/features/integrations/components/resource-selection-model"
import type { IntegrationResource } from "@/features/integrations/types"

function resource(overrides: Partial<IntegrationResource> = {}): IntegrationResource {
  return {
    availability: "available",
    connection_id: "connection-1",
    connection_owner_scope: "workspace",
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

  it("keeps parents before alphabetically sorted children", () => {
    const root = resource({ display_name: "Manager", external_id: "100", id: "root" })
    const alphaChild = resource({
      display_name: "Alpha client",
      external_id: "300",
      id: "alpha",
      parent_external_id: "100",
    })
    const zuluChild = resource({
      display_name: "Zulu client",
      external_id: "200",
      id: "zulu",
      parent_external_id: "100",
    })
    const grandchild = resource({
      display_name: "Nested client",
      external_id: "400",
      id: "nested",
      parent_external_id: "200",
    })

    expect(resourcesInHierarchyOrder([grandchild, zuluChild, alphaChild, root])).toEqual([
      root,
      alphaChild,
      zuluChild,
      grandchild,
    ])
  })

  it("hides the full subtree beneath a collapsed manager", () => {
    const root = resource({ external_id: "100", id: "root", metadata: { manager: true } })
    const childManager = resource({
      external_id: "200",
      id: "child-manager",
      metadata: { manager: true },
      parent_external_id: "100",
    })
    const grandchild = resource({
      external_id: "300",
      id: "grandchild",
      parent_external_id: "200",
    })
    const ordered = resourcesInHierarchyOrder([grandchild, childManager, root])

    expect(resourcesWithExpandedParents(ordered, new Set(["100"]))).toEqual([root])
    expect(resourcesWithExpandedParents(ordered, new Set(["200"]))).toEqual([root, childManager])
  })
})
