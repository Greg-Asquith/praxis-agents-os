// apps/web/tests/features/knowledge/status.test.ts

import { describe, expect, it } from "vitest"

import { hasActiveProcessing, KB_STATUS_PRESENTATION } from "@/features/knowledge/status"

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
})
