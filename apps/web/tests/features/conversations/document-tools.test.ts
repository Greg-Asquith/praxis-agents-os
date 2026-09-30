// apps/web/tests/features/conversations/document-tools.test.ts

import { describe, expect, it } from "vitest"

import { documentToolResult } from "@/features/conversations/native-tools/document-tools"

describe("document tool results", () => {
  it("leaves an unrecognised edit result to the generic row", () => {
    // A write_file-shaped result has no revision_number or changes.
    const result = documentToolResult("edit_workbook", {
      file_id: "file-1",
      name: "Regional sales.xlsx",
      revision_id: "revision-2",
      bytes_written: 4096,
    })

    expect(result).toBeNull()
  })
})
