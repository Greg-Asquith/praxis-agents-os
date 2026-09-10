// apps/web/tests/features/knowledge/api/platform-documents.test.ts

import { QueryClient } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"
import { copyDocumentMutationOptions } from "@/features/knowledge/api/copy-document"
import { documentsQueryOptions, knowledgeQueryKeys } from "@/features/knowledge/api/list-documents"
import { platformDocumentQueryOptions } from "@/features/knowledge/api/platform-get-document"
import {
  platformDocumentsQueryOptions,
  platformKnowledgeQueryKeys,
} from "@/features/knowledge/api/platform-list-documents"
import { platformPublishDocumentMutationOptions } from "@/features/knowledge/api/platform-publish-document"
import { platformWithdrawDocumentMutationOptions } from "@/features/knowledge/api/platform-withdraw-document"
import { platformCreateDocumentFromFileMutationOptions } from "@/features/knowledge/api/platform-create-document-from-file"
import { clearActiveWorkspace, setActiveUserId, setActiveWorkspaceSlug } from "@/lib/workspace"
import {
  getFetchRequest,
  getJsonRequestBody,
  jsonResponse,
  stubFetch,
} from "../../../support/fetch-stub"

afterEach(() => {
  clearActiveWorkspace()
  vi.unstubAllGlobals()
})

describe("platform Knowledge API", () => {
  it("filters tenant lists on the server and separates platform management caches", async () => {
    setActiveUserId("admin")
    setActiveWorkspaceSlug("alpha")
    const fetch = stubFetch(jsonResponse({ documents: [], total: 0 }))
    const client = new QueryClient()
    const options = documentsQueryOptions({ scope: "platform", offset: 25, limit: 25 })
    await client.fetchQuery(options)
    const { url } = getFetchRequest(fetch)
    expect(url.searchParams.get("scope")).toBe("platform")
    expect(url.searchParams.get("offset")).toBe("25")
    expect(platformDocumentsQueryOptions().queryKey).not.toEqual(options.queryKey)
    const first = platformDocumentQueryOptions("document").queryKey
    setActiveWorkspaceSlug("beta")
    expect(platformDocumentQueryOptions("document").queryKey).not.toEqual(first)
    client.clear()
  })

  it("requests drafts only through the management endpoint", async () => {
    const fetch = stubFetch(jsonResponse({ id: "draft" }))
    const client = new QueryClient()
    await client.fetchQuery(platformDocumentQueryOptions("draft"))
    expect(getFetchRequest(fetch).url.pathname).toBe("/api/v1/kb/platform/documents/draft")
    client.clear()
  })

  it("publishes the reviewed generation and refreshes every workspace cache", async () => {
    const fetch = stubFetch(jsonResponse({ id: "document" }))
    const client = new QueryClient()
    const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue()
    await client
      .getMutationCache()
      .build(client, platformPublishDocumentMutationOptions(client))
      .execute({ documentId: "document", expectedIngestionVersion: "reviewed-version" })
    const { init, url } = getFetchRequest(fetch)
    expect(url.pathname).toBe("/api/v1/kb/platform/documents/document/publish")
    expect(getJsonRequestBody(init)).toEqual({ expected_ingestion_version: "reviewed-version" })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: knowledgeQueryKeys.all })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: platformKnowledgeQueryKeys.all })
  })

  it("withdrawal refreshes lists, details and searches across workspaces", async () => {
    stubFetch(jsonResponse({ id: "document" }))
    const client = new QueryClient()
    const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue()
    await client
      .getMutationCache()
      .build(client, platformWithdrawDocumentMutationOptions(client))
      .execute("document")
    expect(invalidate).toHaveBeenCalledWith({ queryKey: knowledgeQueryKeys.all })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: platformKnowledgeQueryKeys.all })
  })

  it("pins uploads to the selected platform revision without tenant privacy fields", async () => {
    const fetch = stubFetch(jsonResponse({ id: "document" }))
    const client = new QueryClient()
    await client
      .getMutationCache()
      .build(client, platformCreateDocumentFromFileMutationOptions(client))
      .execute({ file_id: "file", file_revision_id: "revision" })
    const { init, url } = getFetchRequest(fetch)
    expect(url.pathname).toBe("/api/v1/kb/platform/documents/from-file")
    expect(getJsonRequestBody(init)).toEqual({ file_id: "file", file_revision_id: "revision" })
  })

  it("creates independent private workspace copies by default", async () => {
    setActiveWorkspaceSlug("alpha")
    const fetch = stubFetch(jsonResponse({ id: "copy" }))
    const client = new QueryClient()
    const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue()
    const mutation = client.getMutationCache().build(client, copyDocumentMutationOptions(client))
    const workspaceKey = knowledgeQueryKeys.workspace()
    await mutation.execute({ title: "Policy", contentMd: "Canonical content" })
    const { init, url } = getFetchRequest(fetch)
    expect(url.pathname).toBe("/api/v1/kb/documents")
    expect(getJsonRequestBody(init)).toEqual({
      title: "Policy",
      content_md: "Canonical content",
      is_private: true,
    })
    expect(new Headers(init.headers).get("X-Workspace")).toBe("alpha")
    expect(invalidate).toHaveBeenCalledWith({ queryKey: workspaceKey })
  })

  it("does not refresh caches after a rejected publication", async () => {
    stubFetch(jsonResponse({ detail: "Review the latest content" }, { status: 409 }))
    const client = new QueryClient()
    const invalidate = vi.spyOn(client, "invalidateQueries")
    await expect(
      client
        .getMutationCache()
        .build(client, platformPublishDocumentMutationOptions(client))
        .execute({ documentId: "document", expectedIngestionVersion: "stale" })
    ).rejects.toThrow("Review the latest content")
    expect(invalidate).not.toHaveBeenCalled()
  })
})
