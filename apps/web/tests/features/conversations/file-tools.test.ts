// apps/web/tests/features/conversations/file-tools.test.ts

import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { FileToolRow } from "@/features/conversations/components/file-tool-row"
import { describe, expect, it } from "vitest"

import {
  fileEntityFromGeneratedImage,
  fileEntityFromReadUrlResult,
  fileEntityFromRuntimeFile,
  fileEntityFromWriteResult,
  generateImageResult,
  listFilesResult,
  readFileContentResult,
  readFileImageResult,
  readFileUrlResult,
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

it("renders wrapped platform File text in the transcript without exposing the wrapper", () => {
  const html = renderToStaticMarkup(
    createElement(FileToolRow, {
      activity: {
        id: "read",
        kind: "result",
        status: "completed",
        name: "read_file",
        result: {
          ...fileTextSlice,
          media_type: "text/plain",
          content: {
            node: "praxis_untrusted",
            source_kind: "file",
            source_ref: "file:shared/revision:published",
            content: "<p>Delivery policy</p>",
          },
        },
      },
      defaultOpen: true,
    })
  )
  expect(html).toContain('aria-label="Read File"')
  expect(html).toContain("&lt;p&gt;Delivery policy&lt;/p&gt;")
  expect(html).not.toContain("<p>Delivery policy</p>")
  expect(html).not.toContain("praxis_untrusted")
})
