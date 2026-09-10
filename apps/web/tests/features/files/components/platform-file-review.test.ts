import { createElement, type PropsWithChildren } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"
import { PlatformFileReview } from "@/features/files/components/platform-file-review"
import { platformFilePreviewQueryOptions } from "@/features/files/api/platform-file-preview"
import type { WorkspaceFile } from "@/features/files/types"

vi.mock("@/features/files/components/file-content-view", () => ({
  FileContentView: ({ content }: PropsWithChildren<{ content: string }>) =>
    createElement("pre", null, content),
}))
const file: WorkspaceFile = {
  id: "draft",
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
  current_revision_id: "reviewed",
  revision_count: 1,
  processing_status: "ready",
  processing_error: null,
  created_at: "2026-09-10",
  updated_at: "2026-09-10",
}
function renderReview(target: WorkspaceFile, previewLoaded: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  if (previewLoaded)
    client.setQueryData(platformFilePreviewQueryOptions(target).queryKey, {
      blob: null,
      content: "Reviewed content",
      mediaType: "text/markdown",
    })
  const html = renderToStaticMarkup(
    createElement(QueryClientProvider, {
      client,
      children: createElement(PlatformFileReview, { file: target }),
    })
  )
  client.clear()
  return html
}
describe("platform file status", () => {
  it("shows processing without publication controls", () => {
    const html = renderReview({ ...file, processing_status: "processing" }, false)
    expect(html).toContain("Preparing this file")
    expect(html).toContain("not yet available in other workspaces")
    expect(html).not.toContain("<button")
  })
  it("shows ready content without lifecycle actions", () => {
    const html = renderReview(file, true)
    expect(html).toContain("Reviewed content")
    expect(html).not.toContain("<button")
    expect(html).not.toContain("Publish to")
  })
  it("shows processing failure as an alert", () => {
    const html = renderReview(
      { ...file, processing_status: "error", processing_error: "File conversion failed" },
      false
    )
    expect(html).toContain('role="alert"')
    expect(html).toContain("File conversion failed")
    expect(html).not.toContain("Loading preview")
  })
  it("describes published availability", () => {
    const html = renderReview(
      { ...file, is_published: true, published_revision_id: "reviewed" },
      true
    )
    expect(html).toContain("available in every workspace")
    expect(html).not.toContain("Withdraw")
  })
})
