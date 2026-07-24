// apps/web/tests/features/knowledge/components/manual-document-form-model.test.ts

import { describe, expect, it } from "vitest"

import {
  buildManualDocumentPayload,
  validateManualDocumentForm,
} from "@/features/knowledge/components/manual-document-form-model"

describe("manual knowledge document form", () => {
  it("requires a title and content", () => {
    expect(
      validateManualDocumentForm({ content: " ", isPrivate: false, title: "" }).map(
        (entry) => entry.message
      )
    ).toEqual(["Title is required.", "Content is required."])
  })

  it("trims valid values and preserves privacy", () => {
    expect(
      buildManualDocumentPayload({
        content: "  # Runbook  ",
        isPrivate: true,
        title: "  Operations  ",
      })
    ).toEqual({
      content_md: "# Runbook",
      is_private: true,
      title: "Operations",
    })
  })
})
