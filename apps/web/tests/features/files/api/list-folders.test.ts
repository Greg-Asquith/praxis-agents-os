import { afterEach, describe, expect, it } from "vitest"

import { foldersQueryOptions } from "@/features/files/api/list-folders"
import { clearActiveWorkspace, setActiveUserId, setActiveWorkspaceSlug } from "@/lib/workspace"

afterEach(() => {
  clearActiveWorkspace()
})

describe("folder query keys", () => {
  it("isolates cached folders by user and workspace", () => {
    setActiveUserId("user-1")
    setActiveWorkspaceSlug("acme")
    const acmeKey = foldersQueryOptions().queryKey

    setActiveWorkspaceSlug("globex")
    const globexKey = foldersQueryOptions().queryKey

    expect(acmeKey).toEqual(["files", "user-1", "acme", "folders"])
    expect(globexKey).toEqual(["files", "user-1", "globex", "folders"])
    expect(globexKey).not.toEqual(acmeKey)
  })
})
