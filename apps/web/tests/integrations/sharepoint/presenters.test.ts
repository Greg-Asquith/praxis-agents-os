// apps/web/tests/integrations/sharepoint/presenters.test.ts

import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeAll, describe, expect, it } from "vitest"

import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import { loadIntegrationUiModules } from "@/integrations/registry"
import { parseFileContent } from "@/integrations/sharepoint/lib/file-content"
import { parseFindResults } from "@/integrations/sharepoint/lib/find-results"
import { itemRows } from "@/integrations/sharepoint/lib/items"

const node = (content: string) => ({
  node: "praxis_untrusted",
  source_kind: "sharepoint_drive_item",
  source_ref: "drive:item",
  content,
})
const item = {
  reference: {
    version: 1,
    entity_kind: "sharepoint_drive_item",
    drive_id: "opaque-drive-id",
    item_id: "opaque-item-id",
    label: "SharePoint item",
    kind: "file",
  },
  name: node("Monthly report.txt"),
  kind: "file",
  path: node("/drive/root:/Reports"),
  size_bytes: 1024,
  content_type: node("text/plain"),
  modified_at: node("2026-09-15T10:00:00Z"),
  web_url: node("https://example.sharepoint.com/Documents/Monthly%20report.txt"),
}
const success = (data: unknown) => ({
  provider_key: "sharepoint",
  external_id: "opaque-drive-id",
  display_name: "Operations library",
  status: "success",
  data,
})
const failure = {
  provider_key: "sharepoint",
  external_id: "opaque-other-drive",
  display_name: "Other library",
  status: "error",
  data: null,
  error_code: "access_denied",
  error_message: "Library access denied. Check your SharePoint permissions.",
}
const listing = { items: [item], count: 1, has_more: false }
const fileContent = {
  name: item.name,
  content_type: item.content_type,
  size_bytes: item.size_bytes,
  modified_at: item.modified_at,
  web_url: item.web_url,
  markdown: node("# Monthly report\n\nRevenue **increased**."),
  truncated: false,
  offset: 0,
  end_offset: 41,
  total_bytes: 41,
  limit_reached: false,
  source: "text",
}

function renderResults(
  results: unknown[],
  status: "completed" | "running" = "completed",
  name = "sharepoint_list_folder",
  args?: unknown
) {
  return renderCustomToolCallRow({
    activity: {
      id: "call",
      kind: "result",
      name,
      args,
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

function render(node: ReactNode) {
  return renderToStaticMarkup(createElement("div", null, node))
}

describe("SharePoint presenters", () => {
  beforeAll(async () => {
    await loadIntegrationUiModules(["sharepoint"])
  })

  const url = "https://example.sharepoint.com/:w:/s/Operations/shared-file"
  const renderLinks = (results: unknown[]) =>
    renderResults(results, "completed", "sharepoint_open_link", { url })

  it("shows a resolved link with a guarded citation and no private fields", () => {
    const html = render(renderLinks([success(item), failure]))
    expect(html).toContain("Monthly report.txt")
    expect(html).toContain(`href="${item.web_url.content}"`)
    expect(html).toContain('rel="noopener noreferrer"')
    expect(html).toContain(failure.error_message)
    expect(html).not.toContain(`href="${url}"`)
    expect(html).not.toMatch(/praxis_untrusted|source_ref|opaque-drive-id|opaque-item-id/)
  })

  it("escapes library recovery hints and excludes private failure fields", () => {
    const html = render(
      renderLinks([
        {
          ...failure,
          error_code: "library_not_selected",
          data: {
            library: node('<a href="https://example.com">Operations</a> / Documents'),
            reference: item.reference,
            "@microsoft.graph.downloadUrl": "https://example.com/private-download",
          },
        },
      ])
    )
    expect(html).toContain(
      "&lt;a href=&quot;https://example.com&quot;&gt;Operations&lt;/a&gt; / Documents"
    )
    expect(html).not.toMatch(/<a\b|private-download|opaque-item-id|source_ref/)
  })

  it.each([
    [0, 65536, 1153434, "Showing the first 64.0 KB of 1.1 MB"],
    [3145728, 3211264, 4194304, "Showing 64.0 KB starting 3.0 MB into the file"],
  ])("shows a readable file position starting at %i", (offset, end_offset, total_bytes, label) => {
    const html = render(
      renderResults(
        [
          success({
            ...fileContent,
            offset,
            end_offset,
            total_bytes,
            truncated: true,
            hint: "Showing bytes 131072-196608; call sharepoint_read_file with offset=196608",
          }),
        ],
        "completed",
        "sharepoint_read_file"
      )
    )
    expect(html).toContain(label)
    expect(html).not.toMatch(/Showing bytes|offset=/)
  })

  it("renders hostile file content as text and sanitises executable Markdown", () => {
    const html = render(
      renderResults(
        [
          success({
            ...fileContent,
            name: node('<img src=x onerror="alert(1)">.txt'),
            markdown: node(
              [
                "Revenue **increased**.",
                '<ScRiPt>alert("executed")</ScRiPt>',
                '<iframe src="https://example.com/embed"></iframe>',
                '<img src="x" onerror="alert(1)">',
                "[Unsafe action](javascript:alert%281%29)",
              ].join("\n\n")
            ),
          }),
        ],
        "completed",
        "sharepoint_read_file"
      )
    )
    expect(html).toMatch(/<strong[^>]*>increased<\/strong>/)
    expect(html).toContain("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;.txt")
    expect(html).not.toMatch(/<script|<iframe|<img[^>]+onerror|href="javascript:/i)
  })

  it("projects only file content display fields", () => {
    const data = {
      ...fileContent,
      markdown: "",
      size_bytes: 0,
      end_offset: 0,
      total_bytes: 0,
      connection_id: "private-connection",
      "@microsoft.graph.downloadUrl": "https://example.com/private-download",
    }
    expect(parseFileContent(data)).toEqual({
      contentType: "text/plain",
      endOffset: 0,
      limitReached: false,
      offset: 0,
      totalBytes: 0,
      markdown: "",
      name: "Monthly report.txt",
      sizeBytes: 0,
      truncated: false,
      webUrl: item.web_url.content,
    })
  })

  it.each([
    { size_bytes: -1 },
    { offset: 42 },
    { markdown: { ...node("text"), source_ref: null } },
  ])("falls back for malformed file fields: %j", (fields) => {
    expect(
      renderResults([success({ ...fileContent, ...fields })], "completed", "sharepoint_read_file")
    ).toBeNull()
  })

  const found = {
    name: item.name,
    web_url: item.web_url,
    total_bytes: 4194304,
    limit_reached: false,
    matches: [{ offset: 3145728, excerpt: node("Annual REVENUE increased.") }],
    count: 1,
    has_more: false,
  }
  const renderFind = (results: unknown[], args: unknown = { query: "revenue" }) =>
    renderResults(results, "completed", "sharepoint_find_in_file", args)

  it("emphasises literal matches in hostile excerpts as escaped text", () => {
    const excerpt = '<script>alert(1)</script> A.*[B] <img src=x onerror="alert(1)">'
    const html = render(
      renderFind(
        [
          success({
            ...found,
            name: node("<iframe>report</iframe>"),
            matches: [{ offset: 0, excerpt: node(excerpt) }],
          }),
        ],
        { query: "a.*[b]" }
      )
    )
    expect(html).toContain("&lt;script&gt;alert(1)&lt;/script&gt;")
    expect(html).toContain("<strong>A.*[B]</strong>")
    expect(html).not.toMatch(/<script|<img|<iframe/)
  })

  it.each([
    ["İstanbul REVENUE increased", "revenue", "İstanbul <strong>REVENUE</strong> increased"],
    ["🌍 RÉSUMÉ attached", "résumé", "🌍 <strong>RÉSUMÉ</strong> attached"],
  ])("preserves original characters in matches: %s", (excerpt, query, expected) => {
    const html = render(
      renderFind([success({ ...found, matches: [{ offset: 0, excerpt }] })], { query })
    )
    expect(html).toContain(expected)
  })

  it("projects only public find-in-file fields", () => {
    const data = {
      ...found,
      connection_id: "private-connection",
      matches: [{ offset: 3145728, excerpt: node("REVENUE"), secret: "private-secret" }],
    }
    expect(parseFindResults(data)).toEqual({
      name: "Monthly report.txt",
      webUrl: item.web_url.content,
      hasMore: false,
      limitReached: false,
      matches: [{ offset: 3145728, excerpt: "REVENUE" }],
    })
  })

  it.each([
    { count: 2 },
    { matches: [{ offset: 4194304, excerpt: "text" }] },
    {
      matches: Array.from({ length: 26 }, (_, offset) => ({ offset, excerpt: "text" })),
      count: 26,
    },
  ])("falls back for malformed find results: %j", (fields) => {
    expect(renderFind([success({ ...found, ...fields })])).toBeNull()
  })

  it("renders partial folder results through the registry without private fields", () => {
    const html = render(renderResults([success(listing), failure]))
    expect(html).toContain("Monthly report.txt")
    expect(html).toContain(failure.error_message)
    expect(html).not.toMatch(/praxis_untrusted|source_ref|opaque-drive-id|opaque-other-drive/)
  })

  it("projects only public fields into folder table rows", () => {
    const record = {
      ...item,
      connection_id: "private-connection",
      "@microsoft.graph.downloadUrl": "https://example.com/private-download",
    }
    expect(itemRows([record])).toEqual([
      {
        name: "Monthly report.txt",
        kind: "File",
        path: "/drive/root:/Reports",
        size_bytes: 1024,
        content_type: "text/plain",
        modified_at: "2026-09-15T10:00:00Z",
        web_url: item.web_url.content,
      },
    ])
  })

  it.each([
    ["sharepoint_open_link", "javascript:alert(1)"],
    ["sharepoint_list_folder", "data:text/html,unsafe"],
    ["sharepoint_read_file", "//example.com/file"],
  ])("does not activate unsafe citations in %s", (tool, webUrl) => {
    const data =
      tool === "sharepoint_list_folder"
        ? { ...listing, items: [{ ...item, web_url: node(webUrl) }] }
        : tool === "sharepoint_read_file"
          ? { ...fileContent, web_url: node(webUrl) }
          : { ...item, web_url: node(webUrl) }
    const html = render(renderResults([success(data)], "completed", tool, { url }))
    expect(html).toContain("Monthly report.txt")
    expect(html).not.toContain(`href="${webUrl}"`)
  })

  it.each([
    { count: 2 },
    { items: [{ ...item, kind: "shortcut" }] },
    { items: [{ ...item, size_bytes: 1.5 }] },
    { items: [{ ...item, name: { content: "unframed" } }] },
    { items: Array.from({ length: 201 }, () => item), count: 201 },
  ])("rejects malformed folder listings: %j", (overrides) => {
    expect(renderResults([success({ ...listing, ...overrides })])).toBeNull()
  })

  it("escapes hostile search queries and item text", () => {
    const html = render(
      renderResults(
        [
          success({
            items: [{ ...item, name: node("<script>unsafe</script>"), internal: "private-token" }],
            count: 1,
          }),
        ],
        "completed",
        "sharepoint_search_files",
        { query: '<img src=x onerror="alert(1)">' }
      )
    )
    expect(html).toContain("&lt;img")
    expect(html).toContain("&lt;script&gt;")
    expect(html).not.toMatch(/<img|<script|private-token|opaque-/)
  })

  it.each([
    { items: [item], count: 2 },
    { items: Array.from({ length: 26 }, () => item), count: 26 },
  ])("falls back for malformed search results: %j", (data) => {
    expect(
      renderResults(
        [success({ items: [item], count: 1 }), success(data)],
        "completed",
        "sharepoint_search_files"
      )
    ).toBeNull()
  })
})
