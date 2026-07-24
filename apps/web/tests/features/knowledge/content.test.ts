// apps/web/tests/features/knowledge/content.test.ts

import { describe, expect, it } from "vitest"

import { knowledgeContentText } from "@/features/knowledge/content"

describe("knowledge content", () => {
  it("renders plain and structured untrusted content without parsing marker text", () => {
    expect(knowledgeContentText("Manual content")).toBe("Manual content")
    expect(
      knowledgeContentText({
        node: "praxis_untrusted",
        source_kind: "kb",
        source_ref: "chunk:one",
        content: "External content",
      })
    ).toBe("External content")
    expect(knowledgeContentText(null)).toBeNull()
  })
})
