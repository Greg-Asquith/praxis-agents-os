// apps/web/tests/integrations/sharepoint/presenters.test.ts

import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeAll, describe, expect, it } from "vitest"

import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import { loadIntegrationUiModules } from "@/integrations/registry"
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

function renderResults(results: unknown[], status: "completed" | "running" = "completed") {
  return renderCustomToolCallRow({
    activity: {
      id: "call",
      kind: "result",
      name: "sharepoint_list_folder",
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

describe("SharePoint folder results", () => {
  beforeAll(async () => {
    await loadIntegrationUiModules(["sharepoint"])
  })

  it.each(["success", "error", "partial"])("renders %s through the registry", (mode) => {
    const entries = [success(listing), failure].filter(
      (entry) => mode === "partial" || entry.status === mode
    )
    const row = renderResults(entries)
    expect(row).not.toBeNull()
    const html = render(row)
    if (mode !== "error") {
      expect(html).toContain("Monthly report.txt")
      expect(html).toContain("Operations library")
      expect(html).toContain("1 item")
      expect(html).toContain('href="https://example.sharepoint.com/Documents/Monthly%20report.txt"')
      expect(html).toContain('rel="noopener noreferrer"')
    }
    if (mode !== "success") expect(html).toContain(failure.error_message)
    expect(html).not.toMatch(/praxis_untrusted|source_ref|opaque-drive-id|opaque-other-drive/)
  })

  it("shows file and folder metadata in the shared table", () => {
    const html = render(
      renderResults([
        success({
          items: [item, { ...item, name: node("Invoices"), kind: "folder", size_bytes: 0 }],
          count: 2,
          has_more: false,
        }),
      ])
    )
    for (const text of [
      "File",
      "Folder",
      "Invoices",
      "Size (bytes)",
      "1,024",
      "Modified",
      "text/plain",
      "/drive/root:/Reports",
      "2 items",
    ])
      expect(html).toContain(text)
    expect(html).not.toContain("More items are available")
  })

  it("shows empty folders and an empty library result", () => {
    expect(render(renderResults([success({ items: [], count: 0, has_more: false })]))).toContain(
      "No files or folders found."
    )
    expect(render(renderResults([]))).toContain("No libraries returned a result.")
  })

  it.each([{ items: [] }, { items: [item] }])(
    "preserves has_more copy: $items.length items",
    ({ items }) => {
      const html = render(renderResults([success({ items, count: items.length, has_more: true })]))
      expect(html).toContain("More items are available in this folder.")
      expect(html).not.toContain("No files or folders found.")
    }
  )

  it("shows loading copy", () => {
    expect(render(renderResults([], "running"))).toContain("Listing files and folders…")
  })

  it("contains long text and projects only public fields into table rows", () => {
    const long = "long".repeat(500)
    const record = {
      ...item,
      name: node(long),
      connection_id: "private-connection",
      internal: { token: "private-token" },
      "@microsoft.graph.downloadUrl": "https://example.com/private-download",
    }
    expect(itemRows([record])).toEqual([
      {
        name: long,
        kind: "File",
        path: "/drive/root:/Reports",
        size_bytes: 1024,
        content_type: "text/plain",
        modified_at: "2026-09-15T10:00:00Z",
        web_url: item.web_url.content,
      },
    ])
    const html = render(renderResults([success({ ...listing, items: [record] })]))
    expect(html).toContain(long)
    expect(html).toContain("truncate")
    expect(html).toContain("table-fixed")
    expect(html).not.toMatch(
      /praxis_untrusted|source_ref|opaque-item-id|private-connection|private-token|private-download/
    )
  })

  it.each(["javascript:alert(1)", "data:text/html,unsafe"])(
    "does not activate unsafe citation %s",
    (url) => {
      const html = render(
        renderResults([
          success({
            ...listing,
            items: [{ ...item, name: node("<script>alert(1)</script>"), web_url: node(url) }],
          }),
        ])
      )
      expect(html).toContain("&lt;script&gt;")
      expect(html).not.toContain("<script>")
      expect(html).not.toContain(`href="${url}"`)
    }
  )

  it("preserves long citation URLs in full", () => {
    const url = `https://example.sharepoint.com/Documents/report.txt?value=${"a".repeat(7000)}`
    const html = render(
      renderResults([success({ ...listing, items: [{ ...item, web_url: node(url) }] })])
    )
    expect(html).toContain(`href="${url}"`)
  })

  it.each([null, [null], [{}], [{ ...item, name: 7 }]].map((items) => ({ items })))(
    "rejects malformed item lists: $items",
    ({ items }) => {
      expect(renderResults([success({ ...listing, items })])).toBeNull()
    }
  )

  it.each(["name", "path", "content_type", "modified_at", "web_url"])(
    "enforces text types for %s",
    (field) => {
      for (const invalid of [7, null, { content: "unframed" }, { ...node("text"), content: 7 }]) {
        expect(
          renderResults([success({ ...listing, items: [{ ...item, [field]: invalid }] })])
        ).toBeNull()
      }
      expect(
        renderResults([success({ ...listing, items: [{ ...item, [field]: "plain text" }] })])
      ).not.toBeNull()
    }
  )

  it.each(["1024", -1, 1.5, Infinity, NaN, null])("rejects invalid sizes: %s", (size) => {
    expect(
      renderResults([success({ ...listing, items: [{ ...item, size_bytes: size }] })])
    ).toBeNull()
  })

  it.each(["shortcut", "File", null, node("file")])("rejects invalid kinds: %s", (kind) => {
    expect(renderResults([success({ ...listing, items: [{ ...item, kind }] })])).toBeNull()
  })

  it.each([
    { count: "1" },
    { count: -1 },
    { count: 2 },
    { has_more: "false" },
    { has_more: null },
    { items: Array.from({ length: 201 }, () => item), count: 201 },
  ])("rejects malformed folder metadata: %s", (overrides) => {
    expect(renderResults([success({ ...listing, ...overrides })])).toBeNull()
  })
})
