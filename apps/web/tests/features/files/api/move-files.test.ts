import { QueryClient } from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { filesQueryKeys } from "@/features/files/api/list-files"
import { moveFilesMutationOptions } from "@/features/files/api/move-files"
import { setActiveWorkspaceSlug } from "@/lib/workspace"
import {
  getFetchRequest,
  getJsonRequestBody,
  jsonResponse,
  stubFetch,
} from "../../../support/fetch-stub"

beforeEach(() => {
  setActiveWorkspaceSlug("acme")
})

afterEach(() => {
  setActiveWorkspaceSlug(null)
  vi.unstubAllGlobals()
})

describe("move files mutation", () => {
  it("updates file details and invalidates file and folder lists", async () => {
    const movedFile = { id: "file-1", name: "Moved.txt" }
    const fetchStub = stubFetch(jsonResponse({ files: [movedFile] }))
    const queryClient = new QueryClient()
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue()
    const mutation = queryClient
      .getMutationCache()
      .build(queryClient, moveFilesMutationOptions(queryClient))

    await mutation.execute({ fileIds: ["file-1"], folderId: "folder-1" })

    const { init, url } = getFetchRequest(fetchStub)
    expect(url.href).toBe("http://localhost:8000/api/v1/files/move")
    expect(init).toMatchObject({ credentials: "include", method: "POST" })
    expect(getJsonRequestBody(init)).toEqual({
      file_ids: ["file-1"],
      folder_id: "folder-1",
    })
    expect(new Headers(init.headers).get("X-Workspace")).toBe("acme")
    expect(queryClient.getQueryData(filesQueryKeys.detail("file-1"))).toEqual(movedFile)
    expect(invalidate).toHaveBeenCalledWith({ queryKey: filesQueryKeys.lists() })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: filesQueryKeys.folders() })
  })

  it("does not invalidate caches when the request fails", async () => {
    stubFetch(jsonResponse({ detail: "Move failed" }, { status: 409 }))
    const queryClient = new QueryClient()
    const invalidate = vi.spyOn(queryClient, "invalidateQueries")
    const mutation = queryClient
      .getMutationCache()
      .build(queryClient, moveFilesMutationOptions(queryClient))

    await expect(mutation.execute({ fileIds: ["file-1"], folderId: null })).rejects.toThrow(
      "Move failed"
    )
    expect(invalidate).not.toHaveBeenCalled()
  })
})
