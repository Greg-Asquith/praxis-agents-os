// apps/web/tests/features/knowledge/status.test.ts

import { describe, expect, it } from "vitest"

import { canReprocessDocument, hasActiveProcessing } from "@/features/knowledge/status"
import type { KbProcessingStatus, KbSourceType } from "@/features/knowledge/types"

describe("knowledge processing status", () => {
  it("polls only while at least one document is active", () => {
    expect(hasActiveProcessing([{ status: "pending" }])).toBe(true)
    expect(hasActiveProcessing([{ status: "processing" }, { status: "ready" }])).toBe(true)
    expect(hasActiveProcessing([{ status: "ready" }, { status: "error" }])).toBe(false)
    expect(hasActiveProcessing([])).toBe(false)
  })

  it.each([
    ["url", "ready", true],
    ["manual", "ready", false],
    ["manual", "error", true],
  ] satisfies [KbSourceType, KbProcessingStatus, boolean][])(
    "allows %s documents in %s status to be processed again: %s",
    (sourceType, status, expected) => {
      expect(canReprocessDocument({ source_type: sourceType, status })).toBe(expected)
    }
  )
})
