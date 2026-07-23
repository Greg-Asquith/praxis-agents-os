import { describe, expect, it } from "vitest"

import { eligibleContextGroupResources } from "@/features/integrations/components/context-group-resource-model"
import type { IntegrationResource } from "@/features/integrations/types"

function resource(overrides: Partial<IntegrationResource> = {}): IntegrationResource {
  return {
    availability: "available",
    connection_id: "connection-1",
    connection_label: "Shared connection",
    connection_owner_scope: "workspace",
    connection_status: "active",
    display_name: "Resource",
    enabled: true,
    external_id: "resource-1",
    first_seen_at: "2026-07-22T12:00:00Z",
    id: "resource-1",
    last_seen_at: "2026-07-22T12:00:00Z",
    metadata: {},
    parent_external_id: null,
    provider_key: "gmail",
    removed_at: null,
    resource_type: "gmail_mailbox",
    writable: false,
    ...overrides,
  }
}

describe("Context Group resource eligibility", () => {
  it("includes eligible workspace-owned resources in a shared workspace", () => {
    const shared = resource()

    expect(eligibleContextGroupResources([shared], false)).toEqual([shared])
  })

  it("excludes otherwise eligible user-owned resources from a shared workspace", () => {
    const personal = resource({ connection_owner_scope: "user" })

    expect(eligibleContextGroupResources([personal], false)).toEqual([])
  })

  it("includes user-owned and workspace-owned resources in a personal workspace", () => {
    const personal = resource({ connection_owner_scope: "user", id: "personal" })
    const workspace = resource({ id: "workspace" })

    expect(eligibleContextGroupResources([personal, workspace], true)).toEqual([
      personal,
      workspace,
    ])
  })

  it.each([false, true])(
    "excludes disabled, unavailable, removed, and inactive resources when personal=%s",
    (isPersonalWorkspace) => {
      const eligible = resource({ id: "eligible" })
      const disabled = resource({ enabled: false, id: "disabled" })
      const unavailable = resource({ availability: "unavailable", id: "unavailable" })
      const removed = resource({ availability: "removed", id: "removed", removed_at: "now" })
      const inactive = resource({ connection_status: "revoked", id: "inactive" })

      expect(
        eligibleContextGroupResources(
          [disabled, unavailable, removed, inactive, eligible],
          isPersonalWorkspace
        )
      ).toEqual([eligible])
    }
  )
})
