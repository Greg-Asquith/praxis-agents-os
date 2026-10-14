// apps/web/tests/features/conversations/attachments.test.ts

import { describe, expect, it } from "vitest"

import {
  chatAttachmentAcceptValue,
  chatAttachmentRefusal,
} from "@/features/conversations/attachments"

describe("chatAttachmentAcceptValue", () => {
  it("offers video in the picker only when video tools are available", () => {
    expect(chatAttachmentAcceptValue(false).split(",")).not.toEqual(
      expect.arrayContaining([".mp4"])
    )
    expect(chatAttachmentAcceptValue(true).split(",")).toEqual(
      expect.arrayContaining([".mp4", ".mov", ".webm", ".pptx"])
    )
  })
})

describe("chatAttachmentRefusal", () => {
  it("refuses dropped video before upload unless video tools are available", () => {
    const video = new File([], "talk.MOV", { type: "video/quicktime" })

    expect(chatAttachmentRefusal(video, false)).toMatch(/Video can't be attached/)
    expect(chatAttachmentRefusal(video, true)).toBeNull()
  })

  it("refuses unknown extensions the picker would hide", () => {
    expect(chatAttachmentRefusal(new File([], "Report.PDF"), false)).toBeNull()
    expect(chatAttachmentRefusal(new File([], "README"), true)).not.toBeNull()
    expect(chatAttachmentRefusal(new File([], "notes.constructor"), true)).not.toBeNull()
  })
})
