import { describe, expect, it } from "vitest"

import { chatAttachmentAcceptValue } from "@/features/conversations/attachments"
import { WORKSPACE_FILE_MIME_TYPES, workspaceFileAcceptValue } from "@/lib/file"

describe("chatAttachmentAcceptValue", () => {
  it("accepts every workspace file extension except video", () => {
    const chatExtensions = chatAttachmentAcceptValue().split(",")
    const expectedExtensions = workspaceFileAcceptValue()
      .split(",")
      .filter((extension) => {
        const contentType = WORKSPACE_FILE_MIME_TYPES[extension.slice(1)]
        return contentType !== undefined && !contentType.startsWith("video/")
      })

    expect(chatExtensions).toEqual(expectedExtensions)
    expect(chatExtensions).toEqual(
      expect.arrayContaining([".pptx", ".ppt", ".doc", ".xls", ".json"])
    )
    expect(chatExtensions).not.toEqual(expect.arrayContaining([".mp4", ".mov"]))
  })
})
