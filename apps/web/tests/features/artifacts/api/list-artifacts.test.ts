import { afterEach, describe, expect, it } from "vitest"

import { artifactsQueryOptions } from "@/features/artifacts/api/list-artifacts"
import { clearActiveWorkspace, setActiveUserId, setActiveWorkspaceSlug } from "@/lib/workspace"

afterEach(() => {
  clearActiveWorkspace()
})

describe("artifactsQueryOptions", () => {
  it("keys the complete server-owned table state", () => {
    setActiveUserId("user-1")
    setActiveWorkspaceSlug("acme")
    const params = {
      limit: 25,
      offset: 50,
      search: "launch",
      sortBy: "title" as const,
      sortDirection: "asc" as const,
    }

    expect(artifactsQueryOptions(params).queryKey).toEqual([
      "artifacts",
      "user-1",
      "acme",
      "list",
      params,
    ])
  })
})
