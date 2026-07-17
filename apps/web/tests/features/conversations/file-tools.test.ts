import { describe, expect, it } from "vitest"

import {
  fileEntityFromRuntimeFile,
  fileEntityFromWriteResult,
  listFilesResult,
} from "@/features/conversations/file-tools"

describe("file tool entities", () => {
  it("preserves the runtime file snapshot used by interactive transcript rows", () => {
    const result = listFilesResult({
      files: [
        {
          id: "file-1",
          name: "Quarterly plan.pdf",
          category: "ingestible_document",
          media_type: "application/pdf",
          processing_status: "ready",
          size_bytes: 4096,
          updated_at: "2026-07-17T12:00:00Z",
        },
      ],
      scratch: [],
      total: 1,
    })

    expect(result).not.toBeNull()
    const file = result?.files[0]
    if (!file) {
      throw new Error("Expected one parsed file")
    }
    expect(fileEntityFromRuntimeFile(file)).toEqual({
      category: "ingestible_document",
      contentType: "application/pdf",
      fileId: "file-1",
      name: "Quarterly plan.pdf",
      processingStatus: "ready",
      sizeBytes: 4096,
      updatedAt: "2026-07-17T12:00:00Z",
    })
  })

  it("rejects malformed entity categories instead of inventing a thumbnail type", () => {
    expect(
      listFilesResult({
        files: [
          {
            id: "file-1",
            name: "Unknown file",
            category: "archive",
            media_type: "application/zip",
            processing_status: "ready",
            size_bytes: 20,
            updated_at: "2026-07-17T12:00:00Z",
          },
        ],
        scratch: [],
        total: 1,
      })
    ).toBeNull()
  })

  it("only creates file entities for durable write outcomes", () => {
    expect(
      fileEntityFromWriteResult({
        destination: "scratch",
        name: "working-notes.md",
        bytes_written: 120,
      })
    ).toBeNull()
    expect(
      fileEntityFromWriteResult({
        destination: "file",
        name: "working-notes.md",
        bytes_written: 120,
        file_id: "file-2",
      })
    ).toEqual({
      fileId: "file-2",
      name: "working-notes.md",
      sizeBytes: 120,
    })
  })
})
