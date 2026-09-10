import { afterEach, describe, expect, it, vi } from "vitest"
import { QueryClient } from "@tanstack/react-query"

import { filesQueryOptions } from "@/features/files/api/list-files"
import { apiRequest } from "@/lib/api/client"
import { clearActiveWorkspace, setActiveUserId, setActiveWorkspaceSlug } from "@/lib/workspace"

vi.mock("@/lib/api/client", () => ({ apiRequest: vi.fn(), setApiRequestHeadersProvider: vi.fn() }))

afterEach(() => {
  clearActiveWorkspace()
  vi.clearAllMocks()
})

describe("file scope queries", () => {
  it("sends scope to the server and keeps each workspace and filter cache separate", async () => {
    vi.mocked(apiRequest).mockResolvedValue({ files: [], total: 0 })
    setActiveUserId("user-1")
    setActiveWorkspaceSlug("acme")
    const platform = filesQueryOptions({ scope: "platform", offset: 25 })
    const workspace = filesQueryOptions({ scope: "workspace", offset: 25 })
    await new QueryClient().fetchQuery(platform)
    expect(vi.mocked(apiRequest).mock.calls[0]?.[0]).toBe("/files/")
    expect(vi.mocked(apiRequest).mock.calls[0]?.[1]?.query?.["scope"]).toBe("platform")
    expect(vi.mocked(apiRequest).mock.calls[0]?.[1]?.query?.["offset"]).toBe(25)
    expect(platform.queryKey).not.toEqual(workspace.queryKey)
    setActiveWorkspaceSlug("globex")
    expect(filesQueryOptions({ scope: "platform", offset: 25 }).queryKey).not.toEqual(
      platform.queryKey
    )
  })
})
