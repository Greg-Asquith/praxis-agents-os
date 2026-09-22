import { describe, expect, it } from "vitest"

import { itemRows, sharePointItem } from "@/integrations/sharepoint/lib/items"
import {
  sharePointCreateFolderArgs,
  sharePointUpdateFileArgs,
  sharePointWriteFileArgs,
  validateSharePointWriteArgs,
} from "@/integrations/sharepoint/lib/write-args"
import { sharePointWriteResult } from "@/integrations/sharepoint/lib/write-results"

const reference = {
  entity_kind: "sharepoint_drive_item",
  drive_id: "private-drive",
  item_id: "private-item",
  kind: "folder",
  label: "Monthly reports",
}
const item = {
  name: "Report.txt",
  path: "/drives/private-drive/root:/Reports",
  kind: "file",
  size_bytes: 1024,
  content_type: "text/plain",
  modified_at: "2026-09-21T10:00:00Z",
  web_url: "https://example.sharepoint.com/report.txt",
  reference,
  version: "private-version",
  uploadUrl: "private-upload-url",
}

describe("SharePoint write argument parsing", () => {
  it.each([
    ["parent", sharePointCreateFolderArgs],
    ["folder", sharePointWriteFileArgs],
  ] as const)("accepts omitted, null, and selected %s destinations", (field, parse) => {
    const base = { name: "Report.txt", content: "Reviewed text" }
    for (const args of [base, { ...base, [field]: null }]) {
      const parsed = parse(args)
      expect(parsed?.destination).toBeNull()
      expect(validateSharePointWriteArgs(parsed)).toBeNull()
    }
    const selected = parse({ ...base, [field]: reference })
    expect(selected?.destination?.value).toEqual(reference)
    expect(validateSharePointWriteArgs(selected)).toBeNull()
  })

  it.each([
    false,
    [],
    "folder",
    {},
    { ...reference, drive_id: "" },
    { ...reference, kind: "other" },
  ])("rejects malformed optional references %j", (folder) => {
    expect(sharePointWriteFileArgs({ name: "Report.txt", content: "Text", folder })).toBeNull()
    expect(sharePointCreateFolderArgs({ name: "Reports", parent: folder })).toBeNull()
  })

  it("keeps replacement identity and version mandatory", () => {
    const base = {
      file: { ...reference, kind: "file" },
      expected_version: "version",
      content: "Text",
    }
    expect(validateSharePointWriteArgs(sharePointUpdateFileArgs(base))).toBeNull()
    for (const patch of [
      { file: null },
      { file: undefined },
      { expected_version: null },
      { expected_version: "" },
      { expected_version: undefined },
    ]) {
      expect(sharePointUpdateFileArgs({ ...base, ...patch })).toBeNull()
    }
    expect(validateSharePointWriteArgs(sharePointUpdateFileArgs({ ...base, content: null }))).toBe(
      "Enter text content or choose a workspace File."
    )
  })

  it("uses the reviewed library only for the matching drive", () => {
    const base = {
      name: "Report.txt",
      content: "Text",
      folder: reference,
      _library: "Operations",
      _target: { drive_id: reference.drive_id },
    }
    expect(sharePointWriteFileArgs(base)?.library).toBe("Operations")
    expect(
      sharePointWriteFileArgs({ ...base, folder: { ...reference, drive_id: "other-drive" } })
        ?.library
    ).toBe("Library containing the selected item")
  })
})

describe("SharePoint public item parsing", () => {
  it("shares decoded public fields without changing the read table projection", () => {
    const parsed = sharePointItem(item)
    expect(parsed).toEqual({
      name: item.name,
      path: item.path,
      kind: "file",
      sizeBytes: 1024,
      contentType: "text/plain",
      modifiedAt: item.modified_at,
      webUrl: item.web_url,
    })
    expect(itemRows([item])).toEqual([
      {
        name: item.name,
        path: item.path,
        kind: "File",
        size_bytes: 1024,
        content_type: "text/plain",
        modified_at: item.modified_at,
        web_url: item.web_url,
      },
    ])
    expect(JSON.stringify(parsed)).not.toMatch(/private-item|private-version|private-upload/)
  })

  it.each(["name", "path", "content_type", "modified_at", "web_url"])(
    "rejects malformed %s in both projections",
    (field) => {
      for (const value of [
        null,
        undefined,
        {},
        [],
        1,
        { node: "praxis_untrusted", content: "Text" },
      ]) {
        const malformed = { ...item, [field]: value }
        expect(itemRows([malformed])).toBeNull()
        expect(sharePointWriteResult({ outcome: "applied", item: malformed })).toBeNull()
      }
    }
  )

  it.each([{ kind: "other" }, { size_bytes: -1 }, { size_bytes: 0.5 }, { size_bytes: Infinity }])(
    "rejects malformed item fields %j",
    (patch) => {
      expect(sharePointItem({ ...item, ...patch })).toBeNull()
      expect(sharePointWriteResult({ outcome: "applied", item: { ...item, ...patch } })).toBeNull()
    }
  )

  it("allows missing item evidence only for failed and unverified results", () => {
    expect(sharePointWriteResult({ outcome: "applied" })).toBeNull()
    for (const outcome of ["failed", "unverified"]) {
      expect(sharePointWriteResult({ outcome })).toEqual({
        outcome,
        item: null,
        detail: null,
        errorCode: null,
      })
    }
  })
})
