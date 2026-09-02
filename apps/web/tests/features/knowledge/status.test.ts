// apps/web/tests/features/knowledge/status.test.ts

import { describe, expect, it } from "vitest"

import {
  canReprocessDocument,
  hasActiveProcessing,
  isRefreshableSource,
  KB_STATUS_PRESENTATION,
} from "@/features/knowledge/status"
import type { KbProcessingStatus, KbSourceType } from "@/features/knowledge/types"

describe("knowledge processing status", () => {
  it("maps every status to operator-facing copy", () => {
    expect(KB_STATUS_PRESENTATION).toEqual({
      pending: { label: "Queued", variant: "outline" },
      processing: { label: "Processing", variant: "warning" },
      ready: { label: "Ready", variant: "success" },
      error: { label: "Failed", variant: "destructive" },
    })
  })

  it("polls only while at least one document is active", () => {
    expect(hasActiveProcessing([{ status: "pending" }])).toBe(true)
    expect(hasActiveProcessing([{ status: "processing" }, { status: "ready" }])).toBe(true)
    expect(hasActiveProcessing([{ status: "ready" }, { status: "error" }])).toBe(false)
    expect(hasActiveProcessing([])).toBe(false)
  })

  it.each([
    ["url", true],
    ["integration", true],
    ["manual", false],
    ["upload", false],
  ] satisfies [KbSourceType, boolean][])(
    "identifies %s documents as refreshable: %s",
    (sourceType, expected) => {
      expect(isRefreshableSource(sourceType)).toBe(expected)
    }
  )

  it.each([
    ["url", "pending", false],
    ["url", "processing", false],
    ["url", "ready", true],
    ["url", "error", true],
    ["integration", "pending", false],
    ["integration", "processing", false],
    ["integration", "ready", true],
    ["integration", "error", true],
    ["manual", "pending", false],
    ["manual", "processing", false],
    ["manual", "ready", false],
    ["manual", "error", true],
    ["upload", "pending", false],
    ["upload", "processing", false],
    ["upload", "ready", false],
    ["upload", "error", true],
  ] satisfies [KbSourceType, KbProcessingStatus, boolean][])(
    "allows %s documents in %s status to be processed again: %s",
    (sourceType, status, expected) => {
      expect(canReprocessDocument({ source_type: sourceType, status })).toBe(expected)
    }
  )
})
