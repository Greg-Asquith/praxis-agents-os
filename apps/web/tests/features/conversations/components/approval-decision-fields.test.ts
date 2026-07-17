import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { ApprovalRequestFields } from "@/features/conversations/components/approval-decision-fields"

describe("ApprovalRequestFields", () => {
  it("title-cases option labels while preserving their submitted values", () => {
    const html = renderToStaticMarkup(
      createElement(ApprovalRequestFields, {
        activityId: "search-1",
        args: { model_provider: "openai" },
        decision: { decision: "pending", edits: {}, message: "" },
        disabled: false,
        fallbackFields: [],
        fields: [
          {
            key: "model_provider",
            label: "Search Provider",
            format: "text",
            editable: true,
            placeholder: "",
            options: ["anthropic", "google", "openai"],
            secondary: false,
          },
        ],
        onEditsChange: () => undefined,
      })
    )

    expect(html).toContain("Openai")
    expect(html).toContain('value="openai"')
    expect(html).not.toContain(">openai<")
  })
})
