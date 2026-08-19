import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { ClassifierToolRow } from "@/features/conversations/components/classifier-tool-row"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  classifierArgs,
  classifierItems,
  classifierResult,
} from "@/features/conversations/native-tools/classifier-tool"

describe("classifier tool row", () => {
  it("renders a completed batch with item context, label counts, and table actions", () => {
    const html = render(
      activity({
        args: {
          instructions: "Route messages by sentiment.",
          items: ["Refund requested", "Wonderful support", "Where is my order?"],
          labels: ["complaint", "praise", "other"],
        },
        result: {
          model: "gpt-5.6-luna",
          model_provider: "openai",
          results: [
            { index: 0, value: "Refund requested", label: "complaint" },
            { index: 1, value: "Wonderful support", label: "praise" },
            { index: 2, value: "Where is my order?", label: "other" },
          ],
        },
      }),
      true
    )

    expect(html).toContain("Classify")
    expect(html).toContain("3 Classified")
    expect(html).toContain('aria-label="Label distribution"')
    expect(html).toContain("complaint · 1")
    expect(html).toContain("praise · 1")
    expect(html).toContain("other · 1")
    expect(html).toContain("Refund requested")
    expect(html).toContain("Wonderful support")
    expect(html).toContain("Where is my order?")
    expect(html).toContain("Classified value")
    expect(html).toContain("Assigned label")
    expect(html).toContain('<col style="width:48px"/>')
    expect(html.match(/<col style="width:auto"\/>/g)).toHaveLength(2)
    expect(html).toContain('aria-label="Copy Report Table"')
    expect(html).toContain('aria-label="Download Report CSV"')
    expect(html).not.toContain('data-slot="tool-field-well"')
  })

  it("renders honest running, failed, and declined states", () => {
    const running = render(
      activity({
        status: "running",
        result: undefined,
      })
    )
    const failed = render(activity({ status: "failed", result: "The helper timed out." }))
    const denied = render(activity({ status: "denied", result: undefined }))

    expect(running).toContain("Classifying 3 items…")
    expect(running).toContain("3 labels: complaint, praise, other")
    expect(running).toContain('aria-busy="true"')
    expect(failed).toContain("Classification failed")
    expect(failed).toContain("The helper timed out.")
    expect(denied).toContain("Classification declined")
    expect(denied).toContain("No items were sent to the helper model.")
  })

  it("fails closed for malformed args and non-closed output labels", () => {
    expect(classifierArgs({ items: ["one"], labels: ["only"] })).toBeNull()
    expect(
      classifierResult(
        { items: ["one"], labels: ["yes", "no"] },
        {
          model: "gpt-5.6-luna",
          model_provider: "openai",
          results: [{ index: 0, label: "injected text" }],
        }
      )
    ).toBeNull()
    expect(
      classifierResult(
        { items: ["one", "two"], labels: ["yes", "no"] },
        {
          model: "gpt-5.6-luna",
          model_provider: "openai",
          results: [
            { index: 1, label: "yes" },
            { index: 0, label: "no" },
          ],
        }
      )
    ).toBeNull()
    expect(
      classifierResult(
        { items: ["one"], labels: ["yes", "no"] },
        {
          model: "gpt-5.6-luna",
          model_provider: "openai",
          results: [{ index: 0, value: "different value", label: "yes" }],
        }
      )
    ).toBeNull()
  })

  it("renders retained code-mode results when nested arguments are not persisted", () => {
    const html = render(
      activity({
        args: undefined,
        result: {
          model: "gpt-5.6-luna",
          model_provider: "openai",
          results: [
            { index: 0, value: "Refund requested", label: "complaint" },
            { index: 1, value: "Wonderful support", label: "praise" },
          ],
        },
      }),
      true
    )

    expect(html).toContain("2 Classified")
    expect(html).toContain("complaint · 1")
    expect(html).toContain("praise · 1")
    expect(html).toContain("Refund requested")
    expect(html).toContain("Wonderful support")
  })

  it("uses the workspace classifier label and item-only arguments", () => {
    const workspaceActivity = activity({
      args: { items: ["London plumber", "boiler repair"] },
      name: "classifier_location_search_term",
      result: {
        model: "gpt-5.6-luna",
        model_provider: "openai",
        results: [
          { index: 0, value: "London plumber", label: "Location" },
          { index: 1, value: "boiler repair", label: "Other" },
        ],
      },
    })
    const html = renderToStaticMarkup(
      createElement(ClassifierToolRow, {
        activity: workspaceActivity,
        defaultOpen: true,
        label: "Location Search Term",
      })
    )

    expect(classifierItems(workspaceActivity.args)).toEqual(["London plumber", "boiler repair"])
    expect(html).toContain("Location Search Term")
    expect(html).toContain("2 Classified")
    expect(html).toContain("London plumber")
  })
})

function render(value: ToolActivity, defaultOpen = false) {
  return renderToStaticMarkup(createElement(ClassifierToolRow, { activity: value, defaultOpen }))
}

function activity(overrides: Partial<ToolActivity>): ToolActivity {
  return {
    id: "classify-1",
    kind: "result",
    name: "classify",
    status: "completed",
    args: {
      items: ["Refund requested", "Wonderful support", "Where is my order?"],
      labels: ["complaint", "praise", "other"],
    },
    result: {
      model: "gpt-5.6-luna",
      model_provider: "openai",
      results: [
        { index: 0, value: "Refund requested", label: "complaint" },
        { index: 1, value: "Wonderful support", label: "praise" },
        { index: 2, value: "Where is my order?", label: "other" },
      ],
    },
    ...overrides,
  }
}
