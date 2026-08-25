import { describe, expect, it } from "vitest"

import { contentTypeForWorkspaceFile, WORKSPACE_FILE_MIME_TYPES } from "@/lib/file"

describe("workspace file MIME types", () => {
  it.each([
    ["report.doc", "application/msword"],
    ["slides.ppt", "application/vnd.ms-powerpoint"],
    ["workbook.xls", "application/vnd.ms-excel"],
  ])("maps %s to %s", (name, expected) => {
    expect(contentTypeForWorkspaceFile({ name, type: "" } as File)).toBe(expected)
  })

  it("exposes legacy Office extensions through the shared map", () => {
    expect(WORKSPACE_FILE_MIME_TYPES).toMatchObject({
      doc: "application/msword",
      ppt: "application/vnd.ms-powerpoint",
      xls: "application/vnd.ms-excel",
    })
  })
})
