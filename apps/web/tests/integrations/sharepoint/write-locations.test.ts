import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeAll, describe, expect, it } from "vitest"

import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import { loadIntegrationUiModules } from "@/integrations/registry"
import { SharePointWriteOutcome } from "@/integrations/sharepoint/components/write-outcome"
import { sharePointWriteLocation } from "@/integrations/sharepoint/lib/write-location"

const reference = {
  version: 1,
  entity_kind: "sharepoint_drive_item",
  drive_id: "private-drive",
  item_id: "private-item",
  kind: "file",
}
const node = (content: string) => ({
  node: "praxis_untrusted",
  source_kind: "sharepoint_drive_item",
  source_ref: "private-source",
  content,
})
const tools = [
  ["sharepoint_create_folder", { name: "Saved folder", parent: null }, "folder"],
  ["sharepoint_write_file", { name: "Saved report.txt", folder: null, content: "Text" }, "file"],
  [
    "sharepoint_update_file",
    { file: reference, expected_version: "version", content: "Text" },
    "file",
  ],
] as const

describe("SharePoint write outcome locations", () => {
  beforeAll(async () => {
    await loadIntegrationUiModules(["sharepoint"])
  })

  it.each(tools)("formats Graph parent paths for %s", (name, args, kind) => {
    for (const [path, location] of [
      ["/drives/private-drive/root:", "Library root"],
      ["/drives/private-drive/root:/", "Library root"],
      ["/drives/private-drive/root:/Reports/Monthly", "/Reports/Monthly"],
      ["", "Location unavailable"],
    ]) {
      for (const outcome of ["applied", "unverified"]) {
        for (const status of outcome === "applied" ? ["success"] : ["success", "error"]) {
          const view = renderCustomToolCallRow({
            activity: {
              id: "write",
              name,
              kind: "call",
              status: "completed",
              args,
              result: {
                results: [
                  {
                    provider_key: "sharepoint",
                    display_name: "Operations library",
                    external_id: "private-drive",
                    status,
                    error_code: outcome === "unverified" ? "unverified_mutation" : null,
                    error_message: null,
                    data: {
                      outcome,
                      item: {
                        name: node("Saved item"),
                        path: node(path ?? ""),
                        kind,
                        size_bytes: 1024,
                        content_type: node("text/plain"),
                        modified_at: node("2026-09-21T10:00:00Z"),
                        web_url: node("https://example.sharepoint.com/saved-item"),
                        reference,
                        uploadUrl: "PRIVATE_UPLOAD_URL",
                      },
                    },
                  },
                ],
              },
            },
            compact: false,
            defaultOpen: true,
            live: false,
            providerKey: "sharepoint",
          })
          expect(view).not.toBeNull()
          const html = renderToStaticMarkup(view)
          expect(html).toContain(location)
          expect(html).toContain("Saved item")
          expect(html).toContain("1.0 KB")
          expect(html).toContain('href="https://example.sharepoint.com/saved-item"')
          expect(html).not.toMatch(/private-|PRIVATE_|\/drives\/|root:|source_ref/)
          if (outcome === "unverified") {
            expect(html).toContain("Unconfirmed")
            expect(html).not.toContain("Success")
          }
        }
      }
    }
  })

  it.each([
    ["/drive/root:/Reports", "/Reports"],
    ["/Reports/Monthly", "/Reports/Monthly"],
    ["/", "Library root"],
    ["/drives/private-drive/items/private-item", "Location unavailable"],
    ["/drives/private-drive/root:invalid", "Location unavailable"],
    ["javascript:alert(1)", "Location unavailable"],
    ["   ", "Location unavailable"],
  ])("handles retained path %j", (path, expected) => {
    expect(sharePointWriteLocation(path)).toBe(expected)
  })

  it("renders a hostile library-relative path as literal text", () => {
    const path = '/drives/private-drive/root:/Reports/<img src=x onerror="alert(1)"> **bold**'
    const html = renderToStaticMarkup(
      createElement(SharePointWriteOutcome, {
        result: {
          outcome: "applied",
          detail: null,
          errorCode: null,
          item: { name: "Saved item", path, sizeBytes: 1, webUrl: null },
        },
        description: null,
      })
    )
    expect(html).toContain("/Reports/&lt;img")
    expect(html).toContain("**bold**")
    expect(html).not.toMatch(/<img|<strong|private-drive|root:/)
  })
})
