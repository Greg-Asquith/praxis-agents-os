// apps/web/tests/features/conversations/video-tools.test.ts

import { describe, expect, it } from "vitest"

import { videoFileReferences } from "@/features/conversations/native-tools/video-tools"

describe("videoFileReferences", () => {
  it("finds video Files at the top level or in a result list", () => {
    expect(
      videoFileReferences({ file_id: "file-1", media_type: "video/mp4", name: "Reel.mp4" })
    ).toEqual([{ fileId: "file-1", name: "Reel.mp4" }])
    expect(
      videoFileReferences({
        clips: [
          { file_id: "file-2", media_type: "video/mp4" },
          { file_id: "file-3", media_type: "image/jpeg" },
        ],
      })
    ).toEqual([{ fileId: "file-2", name: null }])
  })

  it("returns null for results without a video File", () => {
    expect(videoFileReferences({ file_id: "file-1", media_type: "image/png" })).toBeNull()
    expect(videoFileReferences({ files: [{ id: "file-1", media_type: "video/mp4" }] })).toBeNull()
    expect(videoFileReferences("Saved file-1.mp4")).toBeNull()
  })
})
