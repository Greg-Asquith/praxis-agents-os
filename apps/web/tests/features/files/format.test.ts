import { describe, expect, it } from "vitest"

import { fileTypeLabel } from "@/features/files/format"
import type { WorkspaceFile } from "@/features/files/types"

type FileTypeFields = Pick<WorkspaceFile, "category" | "content_type" | "extension">

describe("fileTypeLabel", () => {
  it.each<[FileTypeFields, string]>([
    [{ category: "image", content_type: "image/jpeg", extension: ".jpg" }, "Image"],
    [
      { category: "ingestible_document", content_type: "application/pdf", extension: ".pdf" },
      "PDF",
    ],
    [
      {
        category: "ingestible_document",
        content_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        extension: ".docx",
      },
      "Word",
    ],
    [
      {
        category: "ingestible_document",
        content_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        extension: ".xlsx",
      },
      "Spreadsheet",
    ],
    [
      { category: "editable_text", content_type: "text/markdown; charset=utf-8", extension: ".md" },
      "Markdown",
    ],
  ])("labels $0 as $1", (file, expected) => {
    expect(fileTypeLabel(file)).toBe(expected)
  })
})
