import { describe, expect, it } from "vitest"

import {
  activeContextTargetsKey,
  activeContextTargetsLabel,
  activeContextSelectionFromKey,
  activeContextSelectionKey,
  activeContextSelectionLabel,
  MAX_ACTIVE_CONTEXT_TARGETS,
  toggleActiveContextTarget,
} from "@/features/integrations/active-context"
import type { IntegrationContextGroup, IntegrationResource } from "@/features/integrations/types"

const group: IntegrationContextGroup = {
  created_at: "2026-07-21T12:00:00Z",
  created_by_user_id: "user-1",
  id: "group-1",
  members: [],
  name: "Client X",
  updated_at: "2026-07-21T12:00:00Z",
  workspace_id: "workspace-1",
}

const resource: IntegrationResource = {
  availability: "available",
  connection_id: "connection-1",
  connection_label: "Client X Gmail",
  connection_owner_scope: "user",
  connection_status: "active",
  display_name: "Inbox",
  enabled: true,
  external_id: "inbox-1",
  first_seen_at: "2026-07-21T12:00:00Z",
  id: "resource-1",
  last_seen_at: "2026-07-21T12:00:00Z",
  metadata: {},
  parent_external_id: null,
  provider_key: "gmail",
  removed_at: null,
  resource_type: "mailbox",
  writable: false,
}

describe("active context picker values", () => {
  it("round-trips context groups and resources", () => {
    expect(activeContextSelectionFromKey("group:group-1", [group], [resource])).toEqual({
      context_group_id: "group-1",
      type: "context_group",
    })
    expect(activeContextSelectionFromKey("resource:resource-1", [group], [resource])).toEqual({
      integration_resource_id: "resource-1",
      type: "resource",
    })
    expect(activeContextSelectionFromKey("resource:missing", [group], [resource])).toBeUndefined()
  })

  it("uses stable keys and preserves unavailable selections visibly", () => {
    const selection = { context_group_id: group.id, type: "context_group" } as const
    expect(activeContextSelectionKey(selection)).toBe("group:group-1")
    expect(activeContextSelectionLabel(selection, [group], [resource])).toBe("Client X")
    expect(
      activeContextSelectionLabel(
        { integration_resource_id: "missing", type: "resource" },
        [group],
        [resource]
      )
    ).toBe("Context unavailable")
  })

  it("formats Google Ads account IDs used as resource names", () => {
    const googleAdsResource = {
      ...resource,
      display_name: "1234567890",
      id: "google-ads-resource",
      provider_key: "google_ads",
    }

    expect(
      activeContextSelectionLabel(
        { integration_resource_id: googleAdsResource.id, type: "resource" },
        [],
        [googleAdsResource]
      )
    ).toBe("123-456-7890")
  })

  it("uses order-independent set keys and a compact summary", () => {
    const groupTarget = { context_group_id: group.id, type: "context_group" } as const
    const resourceTarget = { integration_resource_id: resource.id, type: "resource" } as const

    expect(activeContextTargetsKey([groupTarget, resourceTarget])).toBe(
      activeContextTargetsKey([resourceTarget, groupTarget])
    )
    expect(activeContextTargetsLabel([], [group], [resource])).toBe("None")
    expect(activeContextTargetsLabel([groupTarget, resourceTarget], [group], [resource])).toBe(
      "Client X +1 more"
    )
  })

  it("toggles targets without duplicates and enforces the target cap", () => {
    const groupTarget = { context_group_id: group.id, type: "context_group" } as const
    const resourceTarget = { integration_resource_id: resource.id, type: "resource" } as const

    expect(toggleActiveContextTarget([groupTarget], groupTarget)).toEqual([])
    expect(toggleActiveContextTarget([groupTarget], resourceTarget)).toEqual([
      groupTarget,
      resourceTarget,
    ])

    const fullSelection = Array.from({ length: MAX_ACTIVE_CONTEXT_TARGETS }, (_, index) => ({
      integration_resource_id: `resource-${String(index)}`,
      type: "resource" as const,
    }))
    expect(toggleActiveContextTarget(fullSelection, groupTarget)).toBe(fullSelection)
  })
})
