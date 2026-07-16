import { describe, expect, it } from "vitest"

import { shouldShowLiveActivity } from "@/features/conversations/live-activity-visibility"

const EMPTY_STREAM = {
  hasRunningTranscriptTool: false,
  isStreaming: true,
  liveMessageCount: 0,
  liveToolActivityCount: 0,
}

describe("live assistant activity visibility", () => {
  it("hides an empty live shell when the transcript already shows a running tool", () => {
    expect(
      shouldShowLiveActivity({
        ...EMPTY_STREAM,
        hasRunningTranscriptTool: true,
      })
    ).toBe(false)
  })

  it("shows the initial thinking shell before any activity arrives", () => {
    expect(shouldShowLiveActivity(EMPTY_STREAM)).toBe(true)
  })

  it("shows live messages and tool activity whenever either is present", () => {
    expect(
      shouldShowLiveActivity({
        ...EMPTY_STREAM,
        isStreaming: false,
        liveMessageCount: 1,
      })
    ).toBe(true)
    expect(
      shouldShowLiveActivity({
        ...EMPTY_STREAM,
        isStreaming: false,
        liveToolActivityCount: 1,
      })
    ).toBe(true)
  })
})
