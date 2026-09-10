import { QueryClient } from "@tanstack/react-query"
import { afterEach, expect, it, vi } from "vitest"

import { platformUploadFileMutationOptions } from "@/features/files/api/platform-upload-file"
import { platformFilesQueryKeys } from "@/features/files/api/platform-list-files"
import { filesQueryKeys } from "@/features/files/api/list-files"
import { uploadFileDirectly } from "@/lib/api/direct-upload"
import { setActiveWorkspaceSlug } from "@/lib/workspace"
import {
  getFetchRequest,
  getJsonRequestBody,
  jsonResponse,
  stubFetch,
} from "../../../support/fetch-stub"

vi.mock("@/lib/api/direct-upload", () => ({ uploadFileDirectly: vi.fn() }))

afterEach(() => {
  vi.clearAllMocks()
  vi.unstubAllGlobals()
  setActiveWorkspaceSlug(null)
})

it("uploads through the platform boundary and requests durable automatic publication", async () => {
  setActiveWorkspaceSlug("example")
  const upload = { url: "https://files.example.com/upload" }
  const fetch = stubFetch((input) => {
    const url = input instanceof Request ? input.url : input.toString()
    return jsonResponse(
      url.endsWith("/confirm")
        ? { id: "file", scope: "platform", processing_status: "pending" }
        : { grant: { upload, upload_token: "upload-token", max_size_bytes: 100 } }
    )
  })
  const client = new QueryClient()
  const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue()
  const file = new File(["content"], "Guidance.txt", { type: "text/plain" })
  await client
    .getMutationCache()
    .build(client, platformUploadFileMutationOptions(client))
    .execute(file)
  const first = getFetchRequest(fetch)
  expect(first.url.pathname).toBe("/api/v1/files/platform/uploads")
  expect(new Headers(first.init.headers).get("X-Workspace")).toBe("example")
  expect(uploadFileDirectly).toHaveBeenCalledWith(upload, file, 100)
  const confirm = getFetchRequest(fetch, 1)
  expect(confirm.url.pathname).toBe("/api/v1/files/platform/uploads/confirm")
  expect(getJsonRequestBody(confirm.init)).toEqual({
    upload_token: "upload-token",
    publish_when_ready: true,
  })
  expect(invalidate).toHaveBeenCalledWith({ queryKey: platformFilesQueryKeys.workspace() })
  expect(invalidate).toHaveBeenCalledWith({ queryKey: filesQueryKeys.all })
})

it("does not confirm or refresh caches after a failed transfer", async () => {
  const fetch = stubFetch(
    jsonResponse({ grant: { upload: {}, upload_token: "token", max_size_bytes: 100 } })
  )
  vi.mocked(uploadFileDirectly).mockRejectedValueOnce(new Error("Transfer failed"))
  const client = new QueryClient()
  const invalidate = vi.spyOn(client, "invalidateQueries")
  await expect(
    client
      .getMutationCache()
      .build(client, platformUploadFileMutationOptions(client))
      .execute(new File(["content"], "Guidance.txt"))
  ).rejects.toThrow("Transfer failed")
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(invalidate).not.toHaveBeenCalled()
})

it("keeps Knowledge upload revisions unpublished for review", async () => {
  const fetch = stubFetch((input) => {
    const url = input instanceof Request ? input.url : input.toString()
    return jsonResponse(
      url.endsWith("/confirm")
        ? { id: "file", current_revision_id: "revision", scope: "platform" }
        : { grant: { upload: {}, upload_token: "token", max_size_bytes: 100 } }
    )
  })
  const client = new QueryClient()
  const uploaded = await client
    .getMutationCache()
    .build(client, platformUploadFileMutationOptions(client, false))
    .execute(new File(["content"], "Guidance.txt"))
  expect(uploaded.current_revision_id).toBe("revision")
  expect(getJsonRequestBody(getFetchRequest(fetch, 1).init)).toEqual({
    upload_token: "token",
    publish_when_ready: false,
  })
})
