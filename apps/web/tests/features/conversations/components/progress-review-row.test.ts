// apps/web/tests/features/conversations/components/progress-review-row.test.ts

import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { ProgressReviewRow } from "@/features/conversations/components/progress-review-row"

describe("ProgressReviewRow", () => {
  it("renders a steered check as a collapsed card", () => {
    const html = renderToStaticMarkup(
      createElement(ProgressReviewRow, {
        review: {
          id: "review-1",
          verdict: "steer_stop_repeating",
          reason: "It repeated the same search.",
          steerText: "Progress check: try a different approach.",
          reviewNumber: 1,
        },
      })
    )

    expect(html).toContain('aria-expanded="false"')
    expect(html).not.toContain("Progress check: try a different approach.")
  })
})
