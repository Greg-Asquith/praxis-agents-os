// apps/web/tests/integrations/sharepoint/copy-presenter.test.ts

import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeAll, describe, expect, it } from "vitest"

import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import { loadIntegrationUiModules } from "@/integrations/registry"
import { parseCopyResult } from "@/integrations/sharepoint/lib/copy-result"

const node = (content: string) => ({
  node: "praxis_untrusted",
  source_kind: "sharepoint_drive_item",
  source_ref: "private-drive:private-item",
  content,
})
const fileId = "019927a2-1891-7123-8123-0123456789ab"
const source = {
  name: node("Source report.xlsx"),
  kind: "file",
  path: node("/drive/root:/Reports"),
  size_bytes: 2048,
  content_type: node("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
  modified_at: node("2026-09-22T10:00:00Z"),
  web_url: node("https://example.sharepoint.com/Documents/report.xlsx"),
}
const copied = {
  file_id: fileId,
  revision_id: "private-revision",
  reference: { entity_kind: "file", entity_id: fileId },
  name: node("Saved report.xlsx"),
  content_type: source.content_type,
  size_bytes: source.size_bytes,
  source,
  version: "private-version",
}
const success = (data: unknown) => ({
  provider_key: "sharepoint",
  external_id: "private-drive",
  display_name: "Operations library",
  status: "success",
  data,
})

function copyRow(results: unknown[], status: "completed" | "running" = "completed") {
  return renderCustomToolCallRow({
    activity: {
      id: "copy",
      kind: "result",
      name: "sharepoint_copy_to_files",
      status,
      result: { results },
    },
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "sharepoint",
    ui: null,
  })
}

function render(value: ReactNode) {
  return renderToStaticMarkup(createElement("div", null, value))
}

describe("SharePoint copy to Files presenter", () => {
  beforeAll(async () => {
    await loadIntegrationUiModules(["sharepoint"])
  })

  it("shows the source citation and saved File with its size and type", () => {
    const html = render(copyRow([success(copied)]))
    for (const text of [
      "Source report.xlsx",
      "Saved report.xlsx",
      "Operations library",
      "Saved in Files",
      "2.0 KB",
      source.content_type.content,
    ])
      expect(html).toContain(text)
    expect(html).toContain(`href="${source.web_url.content}"`)
    expect(html).toContain('rel="noopener noreferrer"')
    expect(html).toContain(`href="/files?fileId=${fileId}"`)
    expect(html).toContain("Open in Files")
    expect(html).not.toMatch(/private-|praxis_untrusted|source_ref|entity_id/)
  })

  it.each([
    [
      "unsupported_type",
      "Files does not support this file type. Select a supported document, image, or video.",
    ],
    ["too_large", "This file exceeds the copy size limit. Select a smaller file."],
    ["source_changed", "The source file changed. Read it again before copying it."],
  ])("shows %s recovery without rendering private failure data", (error_code, error_message) => {
    const html = render(
      copyRow([
        {
          ...success({ download_url: "https://example.com/private-download", source }),
          status: "error",
          error_code,
          error_message,
        },
      ])
    )
    expect(html).toContain(error_message)
    expect(html).toContain("Failed")
    expect(html).not.toMatch(/private-|Source report|<a\b/)
  })

  it.each([
    "javascript:alert(1)",
    "data:text/html,unsafe",
    "//example.com/unsafe",
    "file:///private",
  ])("keeps the saved File link but excludes unsafe source URL %s", (webUrl) => {
    const html = render(
      copyRow([success({ ...copied, source: { ...source, web_url: node(webUrl) } })])
    )
    expect(html).not.toContain("Open in SharePoint")
    expect(html).not.toContain(webUrl)
    expect(html).toContain(`href="/files?fileId=${fileId}"`)
  })

  it("escapes provider text and excludes private success fields", () => {
    const html = render(
      copyRow([
        success({
          ...copied,
          name: node('<script>alert("saved")</script>'),
          source: {
            ...source,
            name: node('<img src="x" onerror="alert(1)">'),
            "@microsoft.graph.downloadUrl": "https://example.com/private-download",
          },
          upload_url: "https://example.com/private-upload",
          content_hash: "private-hash",
        }),
      ])
    )
    expect(html).toContain("&lt;script&gt;")
    expect(html).toContain("&lt;img")
    expect(html).not.toMatch(/<script|<img|private-|content_hash|downloadUrl/)
  })

  it.each([
    null,
    {},
    { ...copied, file_id: "javascript:alert(1)" },
    { ...copied, file_id: `${fileId}&redirect=https://example.com` },
    { ...copied, file_id: 7 },
    { ...copied, name: { ...node("bad"), source_ref: null } },
    { ...copied, size_bytes: -1 },
    { ...copied, size_bytes: 1.5 },
    { ...copied, size_bytes: Number.POSITIVE_INFINITY },
    { ...copied, content_type: {} },
    { ...copied, source: null },
    { ...copied, source: { ...source, kind: "folder" } },
    { ...copied, source: { ...source, web_url: {} } },
  ])("falls back for malformed copied results: %j", (value) => {
    expect(parseCopyResult(value)).toBeNull()
    expect(copyRow([success(value)])).toBeNull()
  })

  it("retains running and empty states", () => {
    expect(render(copyRow([], "running"))).toContain("Copying SharePoint file to Files…")
    expect(render(copyRow([]))).toContain("No library returned a file to copy.")
  })
})
