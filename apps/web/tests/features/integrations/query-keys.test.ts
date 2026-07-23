import { afterEach, describe, expect, it } from "vitest"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import { integrationResourcesForConnectionQueryOptions } from "@/features/integrations/api/list-resources"
import { setActiveWorkspaceSlug } from "@/lib/workspace"

afterEach(() => {
  setActiveWorkspaceSlug(null)
})

describe("integrationsQueryKeys", () => {
  it("keeps every integration cache scoped to the active workspace", () => {
    setActiveWorkspaceSlug("acme")

    expect(integrationsQueryKeys.providers()).toEqual(["integrations", "acme", "providers"])
    expect(integrationsQueryKeys.connections()).toEqual(["integrations", "acme", "connections"])
    expect(integrationsQueryKeys.resources("connection-1")).toEqual([
      "integrations",
      "acme",
      "detail",
      "connection-1",
      "resources",
    ])
    expect(integrationsQueryKeys.enabledResources()).toEqual([
      "integrations",
      "acme",
      "enabled-resources",
    ])
    expect(integrationsQueryKeys.contextGroups()).toEqual([
      "integrations",
      "acme",
      "context-groups",
    ])
    expect(integrationsQueryKeys.activeContexts()).toEqual([
      "integrations",
      "acme",
      "active-context",
    ])
    expect(integrationsQueryKeys.activeContext("conversation-1")).toEqual([
      "integrations",
      "acme",
      "active-context",
      "conversation-1",
    ])
    expect(integrationsQueryKeys.activeContext("conversation-2")).not.toEqual(
      integrationsQueryKeys.activeContext("conversation-1")
    )
    expect(integrationResourcesForConnectionQueryOptions("connection-1").queryKey).toEqual(
      integrationsQueryKeys.resources("connection-1")
    )
  })
})
