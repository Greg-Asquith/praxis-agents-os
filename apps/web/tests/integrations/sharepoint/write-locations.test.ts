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
describe("SharePoint write outcome locations", () => {
  beforeAll(async () => {
    await loadIntegrationUiModules(["sharepoint"])
  })

  it("renders an unverified write location without private path segments", () => {
    const view = renderCustomToolCallRow({
      activity: {
        id: "write",
        name: "sharepoint_write_file",
        kind: "call",
        status: "completed",
        args: { name: "Saved report.txt", folder: null, content: "Text" },
        result: {
          results: [
            {
              provider_key: "sharepoint",
              display_name: "Operations library",
              external_id: "private-drive",
              status: "error",
              error_code: "unverified_mutation",
              error_message: null,
              data: {
                outcome: "unverified",
                item: {
                  name: node("Saved item"),
                  path: node("/drives/private-drive/root:/Reports/Monthly"),
                  kind: "file",
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
    expect(html).toContain("/Reports/Monthly")
    expect(html).toContain("Unconfirmed")
    expect(html).not.toMatch(/private-|PRIVATE_|\/drives\/|root:|source_ref/)
  })

  it.each([
    ["/drives/private-drive/root:", "Library root"],
    ["/drive/root:/Reports", "/Reports"],
    ["/drives/private-drive/items/private-item", "Location unavailable"],
    ["/drives/private-drive/root:invalid", "Location unavailable"],
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
