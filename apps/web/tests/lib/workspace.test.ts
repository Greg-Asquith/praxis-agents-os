import { afterEach, describe, expect, it } from "vitest"

import {
  activeUserQueryScope,
  activeWorkspaceQueryScope,
  clearActiveWorkspace,
  createWorkspaceScopedQueryKeys,
  setActiveUserId,
  setActiveWorkspaceSlug,
} from "@/lib/workspace"

afterEach(() => {
  clearActiveWorkspace()
})

describe("workspace-scoped query keys", () => {
  it("uses the no-workspace sentinel when no workspace slug is active", () => {
    setActiveWorkspaceSlug(null)
    const userSentinel = ["__", "no", "_", "user", "__"].join("")
    const workspaceSentinel = ["__", "no", "_", "workspace", "__"].join("")

    expect(activeUserQueryScope()).toBe(userSentinel)
    expect(activeWorkspaceQueryScope()).toBe(workspaceSentinel)
    expect(createWorkspaceScopedQueryKeys("agents").workspace()).toEqual([
      "agents",
      userSentinel,
      workspaceSentinel,
    ])
  })

  it("scopes keys by user and workspace", () => {
    setActiveUserId("user-1")
    setActiveWorkspaceSlug("acme")
    const keys = createWorkspaceScopedQueryKeys("agents")
    const params = { includeInactive: true, limit: 50 }

    expect(keys.all).toEqual(["agents"])
    expect(keys.workspace()).toEqual(["agents", "user-1", "acme"])
    expect(keys.details()).toEqual(["agents", "user-1", "acme", "detail"])
    expect(keys.detail("agent-1")).toEqual(["agents", "user-1", "acme", "detail", "agent-1"])
    expect(keys.lists()).toEqual(["agents", "user-1", "acme", "list"])
    expect(keys.list(params)).toEqual(["agents", "user-1", "acme", "list", params])
  })
})
