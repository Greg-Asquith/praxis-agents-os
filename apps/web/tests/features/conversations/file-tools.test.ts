import { describe, expect, it } from "vitest"

import {
  fileEntityFromReadUrlResult,
  fileEntityFromRuntimeFile,
  fileEntityFromWriteResult,
  listFilesResult,
  readFileImageResult,
  readFileUrlResult,
} from "@/features/conversations/native-tools/file-tools"

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

  it("keeps image read metadata when the persisted tool result includes native bytes", () => {
    const metadata = {
      source: "image",
      file_id: "file-3",
      revision_id: "revision-3",
      name: "screenshot.png",
      category: "image",
      media_type: "image/png",
      processing_status: "ready",
    }
    const binary = {
      data: "base64-image-data",
      media_type: "image/png",
      identifier: "file-3",
      kind: "binary",
    }

    expect(readFileImageResult([metadata, binary])).toEqual(metadata)
    expect(readFileImageResult({ return_value: [metadata, binary] })).toEqual(metadata)
  })

  it("preserves image metadata from URL results for the thumbnail path", () => {
    const result = readFileUrlResult({
      mode: "url",
      file_id: "file-4",
      revision_id: "revision-4",
      name: "photo.jpg",
      url: "http://testserver/files/file-4/download",
      expires_at: "2026-07-17T17:07:00Z",
      category: "image",
      media_type: "image/jpeg",
      processing_status: "ready",
    })

    expect(result).not.toBeNull()
    if (!result) {
      throw new Error("Expected a parsed URL result")
    }
    expect(fileEntityFromReadUrlResult(result)).toEqual({
      category: "image",
      contentType: "image/jpeg",
      fileId: "file-4",
      name: "photo.jpg",
      processingStatus: "ready",
    })
  })
})
