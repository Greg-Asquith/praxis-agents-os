import { afterEach, describe, expect, it } from "vitest"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import { integrationResourcesForConnectionQueryOptions } from "@/features/integrations/api/list-resources"
import { clearActiveWorkspace, setActiveUserId, setActiveWorkspaceSlug } from "@/lib/workspace"

afterEach(() => {
  clearActiveWorkspace()
})

describe("integrationsQueryKeys", () => {
  it("keeps every integration cache scoped to the active user and workspace", () => {
    setActiveUserId("user-1")
    setActiveWorkspaceSlug("acme")

    expect(integrationsQueryKeys.providers()).toEqual([
      "integrations",
      "user-1",
      "acme",
      "providers",
    ])
    expect(integrationsQueryKeys.connections()).toEqual([
      "integrations",
      "user-1",
      "acme",
      "connections",
    ])
    expect(integrationsQueryKeys.resources("connection-1")).toEqual([
      "integrations",
      "user-1",
      "acme",
      "detail",
      "connection-1",
      "resources",
    ])
    expect(integrationsQueryKeys.enabledResources()).toEqual([
      "integrations",
      "user-1",
      "acme",
      "enabled-resources",
    ])
    expect(integrationsQueryKeys.contextGroups()).toEqual([
      "integrations",
      "user-1",
      "acme",
      "context-groups",
    ])
    expect(integrationsQueryKeys.activeContexts()).toEqual([
      "integrations",
      "user-1",
      "acme",
      "active-context",
    ])
    expect(integrationsQueryKeys.activeContext("conversation-1")).toEqual([
      "integrations",
      "user-1",
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
