// apps/web/tests/features/memories/components/memory-form-model.test.ts

import { describe, expect, it } from "vitest"

import {
  buildMemoryUpdatePayload,
  validateMemoryForm,
} from "@/features/memories/components/memory-form-model"

describe("memory edit form", () => {
  it("validates required fields, bounds, and expiry", () => {
    const messages = validateMemoryForm({
      title: "",
      content: "x".repeat(2_001),
      importance: 6,
      expiresInDays: "-1",
    }).map((entry) => entry.message)

    expect(messages).toEqual([
      "Title is required.",
      "Memory content must be 2,000 characters or fewer.",
      "Importance must be between 1 and 5.",
      "Expiry must be a whole number of days greater than zero.",
    ])
  })

  it("trims values and includes an optional expiry", () => {
    expect(
      buildMemoryUpdatePayload({
        title: "  Preferred tone  ",
        content: "  Keep answers concise.  ",
        importance: 4,
        expiresInDays: "30",
      })
    ).toEqual({
      title: "Preferred tone",
      content_md: "Keep answers concise.",
      importance: 4,
      expires_in_days: 30,
    })
  })
})
