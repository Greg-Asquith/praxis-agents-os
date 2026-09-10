import { QueryClient } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"

import { copyFileMutationOptions } from "@/features/files/api/copy-file"
import { filesQueryKeys } from "@/features/files/api/list-files"
import { setActiveWorkspaceSlug } from "@/lib/workspace"
import {
  getFetchRequest,
  getJsonRequestBody,
  jsonResponse,
  stubFetch,
} from "../../../support/fetch-stub"

afterEach(() => {
  setActiveWorkspaceSlug(null)
  vi.unstubAllGlobals()
})

describe("workspace File copy", () => {
  it("retains the reviewed revision and retry identity and refreshes workspace caches", async () => {
    setActiveWorkspaceSlug("client-a")
    const fetchStub = stubFetch(jsonResponse({ id: "local-copy", scope: "workspace" }))
    const client = new QueryClient()
    const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue()
    const mutation = client.getMutationCache().build(client, copyFileMutationOptions(client))
    await mutation.execute({
      fileId: "platform-file",
      revisionId: "published-version",
      requestId: "copy-request",
    })
    const { init, url } = getFetchRequest(fetchStub)
    expect(url.pathname).toBe("/api/v1/files/platform-file/copy")
    expect(new Headers(init.headers).get("X-Workspace")).toBe("client-a")
    expect(getJsonRequestBody(init)).toEqual({
      revision_id: "published-version",
      request_id: "copy-request",
    })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: filesQueryKeys.workspace() })
  })

  it("leaves caches unchanged when a withdrawn source is rejected", async () => {
    stubFetch(jsonResponse({ detail: "File not found" }, { status: 404 }))
    const client = new QueryClient()
    const invalidate = vi.spyOn(client, "invalidateQueries")
    const mutation = client.getMutationCache().build(client, copyFileMutationOptions(client))
    await expect(
      mutation.execute({
        fileId: "platform-file",
        revisionId: "published-version",
        requestId: "copy-request",
      })
    ).rejects.toThrow("File not found")
    expect(invalidate).not.toHaveBeenCalled()
  })
})
