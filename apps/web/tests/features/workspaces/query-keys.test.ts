import { afterEach, describe, expect, it } from "vitest"

import {
  activeWorkspaceQueryScope,
  createWorkspaceScopedQueryKeys,
} from "@/features/workspaces/query-keys"
import { setActiveWorkspaceSlug } from "@/features/workspaces/workspace-context"

afterEach(() => {
  setActiveWorkspaceSlug(null)
})

describe("workspace-scoped query keys", () => {
  it("uses the no-workspace sentinel when no workspace slug is active", () => {
    setActiveWorkspaceSlug(null)
    const sentinel = ["__", "no", "_", "workspace", "__"].join("")

    expect(activeWorkspaceQueryScope()).toBe(sentinel)
    expect(createWorkspaceScopedQueryKeys("agents").workspace()).toEqual(["agents", sentinel])
  })

  it("preserves the previous literal key shapes for a fixed root", () => {
    setActiveWorkspaceSlug("acme")
    const keys = createWorkspaceScopedQueryKeys("agents")
    const params = { includeInactive: true, limit: 50 }

    expect(keys.all).toEqual(["agents"])
    expect(keys.workspace()).toEqual(["agents", "acme"])
    expect(keys.details()).toEqual(["agents", "acme", "detail"])
    expect(keys.detail("agent-1")).toEqual(["agents", "acme", "detail", "agent-1"])
    expect(keys.lists()).toEqual(["agents", "acme", "list"])
    expect(keys.list(params)).toEqual(["agents", "acme", "list", params])
  })
})
