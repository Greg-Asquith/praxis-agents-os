import { QueryClient } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { filesQueryKeys } from "@/features/files/api/list-files"
import { moveFilesMutationOptions } from "@/features/files/api/move-files"

const { apiRequest } = vi.hoisted(() => ({ apiRequest: vi.fn() }))

vi.mock("@/lib/api/client", () => ({
  apiRequest,
  setApiRequestHeadersProvider: vi.fn(),
}))

beforeEach(() => {
  apiRequest.mockReset()
})

describe("move files mutation", () => {
  it("updates file details and invalidates file and folder lists", async () => {
    const movedFile = { id: "file-1", name: "Moved.txt" }
    apiRequest.mockResolvedValue({ files: [movedFile] })
    const queryClient = new QueryClient()
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue()
    const mutation = queryClient
      .getMutationCache()
      .build(queryClient, moveFilesMutationOptions(queryClient))

    await mutation.execute({ fileIds: ["file-1"], folderId: "folder-1" })

    expect(apiRequest).toHaveBeenCalledWith("/files/move", {
      body: { file_ids: ["file-1"], folder_id: "folder-1" },
      method: "POST",
    })
    expect(queryClient.getQueryData(filesQueryKeys.detail("file-1"))).toEqual(movedFile)
    expect(invalidate).toHaveBeenCalledWith({ queryKey: filesQueryKeys.lists() })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: filesQueryKeys.folders() })
  })

  it("does not invalidate caches when the request fails", async () => {
    apiRequest.mockRejectedValue(new Error("Move failed"))
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
