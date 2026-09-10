import { QueryClient } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"
import { platformFilePreviewQueryOptions } from "@/features/files/api/platform-file-preview"
import type { WorkspaceFile } from "@/features/files/types"
import { setActiveWorkspaceSlug } from "@/lib/workspace"
import { getFetchRequest, jsonResponse, stubFetch } from "../../../support/fetch-stub"

const file: WorkspaceFile = {
  id: "platform-file",
  scope: "platform",
  workspace_id: null,
  is_published: false,
  can_manage_platform: true,
  published_revision_id: null,
  name: "Guide.md",
  description: null,
  folder_id: null,
  folder_name: null,
  category: "editable_text",
  content_type: "text/markdown",
  extension: "md",
  size_bytes: 10,
  content_hash: "hash",
  current_revision_id: "reviewed-revision",
  revision_count: 1,
  processing_status: "ready",
  processing_error: null,
  created_at: "2026-09-10",
  updated_at: "2026-09-10",
}
afterEach(() => {
  setActiveWorkspaceSlug(null)
  vi.unstubAllGlobals()
})

describe("platform File management", () => {
  it("does not request text content for an audio file", async () => {
    const fetch = stubFetch(jsonResponse({}))
    const client = new QueryClient()
    const result = await client.fetchQuery(
      platformFilePreviewQueryOptions({ ...file, category: "audio", content_type: "audio/mpeg" })
    )
    expect(result).toEqual({ blob: null, content: null, mediaType: null })
    expect(fetch).not.toHaveBeenCalled()
    client.clear()
  })

  it.each(["image", "video"] as const)(
    "fetches %s preview bytes with authentication and a pinned revision",
    async (category) => {
      setActiveWorkspaceSlug("example")
      const fetch = stubFetch(
        new Response("preview", { headers: { "Content-Type": "application/octet-stream" } })
      )
      const client = new QueryClient()
      const options = platformFilePreviewQueryOptions({ ...file, category })
      const result = await client.fetchQuery(options)
      expect(result.blob).toBeInstanceOf(Blob)
      const { init, url } = getFetchRequest(fetch)
      expect(url.pathname).toBe("/api/v1/files/platform/platform-file/preview")
      expect(url.searchParams.get("revision_id")).toBe("reviewed-revision")
      expect(init.credentials).toBe("include")
      expect(init.cache).toBe("no-store")
      expect(new Headers(init.headers).get("X-Workspace")).toBe("example")
      expect(options.gcTime).toBe(0)
      client.clear()
    }
  )
  it.each([
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ])("renders extracted %s using the content response's media type", async (contentType) => {
    const fetch = stubFetch(jsonResponse({ content: "# Guide", content_type: "text/markdown" }))
    const client = new QueryClient()
    const result = await client.fetchQuery(
      platformFilePreviewQueryOptions({
        ...file,
        category: "ingestible_document",
        content_type: contentType,
      })
    )
    expect(result).toEqual({ blob: null, content: "# Guide", mediaType: "text/markdown" })
    const { url } = getFetchRequest(fetch)
    expect(url.pathname).toBe("/api/v1/files/platform/platform-file/content")
    expect(url.searchParams.get("revision_id")).toBe("reviewed-revision")
    client.clear()
  })
})
