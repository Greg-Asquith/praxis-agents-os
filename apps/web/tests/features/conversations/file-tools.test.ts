// apps/web/tests/features/conversations/file-tools.test.ts

import { describe, expect, it } from "vitest"

import {
  fileEntityFromGeneratedImage,
  fileEntityFromRuntimeFile,
  fileEntityFromWriteResult,
  generateImageResult,
  listFilesResult,
  readFileContentResult,
} from "@/features/conversations/native-tools/file-tools"

describe("file tool entities", () => {
  it("preserves generated image metadata for the thumbnail path", () => {
    const result = generateImageResult({
      file_id: "image-1",
      height: 1024,
      media_type: "image/webp",
      name: "paper-cut-fox.webp",
      revision_id: "revision-1",
      size_bytes: 2048,
      width: 1536,
    })

    expect(result).not.toBeNull()
    if (!result) {
      throw new Error("Expected a parsed generated image")
    }
    expect(fileEntityFromGeneratedImage(result)).toEqual({
      category: "image",
      contentType: "image/webp",
      fileId: "image-1",
      name: "paper-cut-fox.webp",
      processingStatus: "ready",
      sizeBytes: 2048,
    })
  })

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
        total: 1,
      })
    ).toBeNull()
  })

  it("creates file entities for durable write outcomes", () => {
    expect(
      fileEntityFromWriteResult({
        name: "working-notes.md",
        bytes_written: 120,
        file_id: "file-2",
        revision_id: "revision-2",
      })
    ).toEqual({
      fileId: "file-2",
      name: "working-notes.md",
      sizeBytes: 120,
    })
  })
})

const fileTextSlice = {
  mode: "content",
  offset: 0,
  end_offset: 12,
  total_bytes: 12,
  truncated: false,
}

describe("file content decoding", () => {
  it.each([
    "Policy text",
    {
      node: "praxis_untrusted",
      source_kind: "file",
      source_ref: "file:shared/revision:published",
      content: "Policy text",
    },
  ])("decodes plain workspace content and wrapped platform content", (content) => {
    expect(readFileContentResult({ ...fileTextSlice, content })).toEqual({
      ...fileTextSlice,
      content: "Policy text",
    })
  })

  it.each([
    null,
    {},
    { node: "praxis_untrusted", content: "Missing source" },
    { node: "praxis_untrusted", source_kind: "file", source_ref: "file:shared", content: 12 },
  ])("rejects malformed content nodes", (content) => {
    expect(readFileContentResult({ ...fileTextSlice, content })).toBeNull()
  })
})
