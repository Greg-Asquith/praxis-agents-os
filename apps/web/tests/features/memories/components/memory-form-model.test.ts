// apps/web/tests/features/memories/components/memory-form-model.test.ts

import { describe, expect, it } from "vitest"

import {
  buildMemoryUpdatePayload,
  MEMORY_CONTENT_LIMITS,
  validateMemoryForm,
} from "@/features/memories/components/memory-form-model"
import type { Memory } from "@/features/memories/types"

describe("memory edit form", () => {
  it("uses the fixed product content limits", () => {
    expect(MEMORY_CONTENT_LIMITS).toEqual({ core: 500, note: 2_000 })
  })

  it("validates required fields, bounds, and expiry", () => {
    const messages = validateMemoryForm(
      {
        title: "",
        content: "x".repeat(501),
        importance: 6,
        expiresInDays: "-1",
      },
      memory()
    ).map((entry) => entry.message)

    expect(messages).toEqual([
      "Title is required.",
      "Memory content must be 500 characters or fewer.",
      "Importance must be between 1 and 5.",
      "Expiry must be a whole number of days greater than zero.",
    ])
  })

  it("trims values and includes an optional expiry", () => {
    expect(
      buildMemoryUpdatePayload(
        {
          title: "  Preferred tone  ",
          content: "  Keep answers concise.  ",
          importance: 4,
          expiresInDays: "30",
        },
        memory()
      )
    ).toEqual({
      title: "Preferred tone",
      content_md: "Keep answers concise.",
      importance: 4,
      expires_in_days: 30,
    })
  })
})

function memory(): Memory {
  return {
    id: "memory-1",
    scope: "agent",
    kind: "core",
    memory_type: "preference",
    status: "active",
    title: "Tone",
    content_md: "Be concise.",
    importance: 3,
    confidence: 0.8,
    effective_confidence: 0.8,
    agent_id: "agent-1",
    agent_name: "Operator",
    user_id: null,
    source: "interactive",
    created_by: "agent",
    created_by_user_id: "user-1",
    expires_at: null,
    superseded_by_id: null,
    archived_at: null,
    archive_reason: null,
    created_at: "2026-07-27T10:00:00Z",
    updated_at: "2026-07-27T10:00:00Z",
  }
}
