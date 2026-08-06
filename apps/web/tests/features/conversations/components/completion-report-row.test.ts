import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import type { ToolActivity } from "@/features/conversations/message-parts"

describe("completion report presenter", () => {
  it("renders a passed verdict with its summary and evidence", () => {
    const html = renderPresenter({
      id: "completion-pass",
      kind: "result",
      name: "report_completion",
      status: "completed",
      result: {
        status: "pass",
        summary: "Hello was said correctly in five languages.",
        evidence: ["English: Hello", "Spanish: Hola"],
      },
    })

    expect(html).toContain('aria-label="Completion check passed"')
    expect(html).toContain('aria-label="Expand results"')
    expect(html).toContain("Summary: Hello was said correctly in five languages.")
    expect(html).toContain("Evidence: 2 Items")
    expect(html).toContain("Passed")
    expect(html).not.toContain("English: Hello")
    expect(html).not.toContain("Spanish: Hola")
  })

  it("renders a failed verdict as needing attention", () => {
    const html = renderPresenter(
      {
        id: "completion-fail",
        kind: "result",
        name: "report_completion",
        status: "completed",
        result: {
          return_value: {
            status: "fail",
            summary: "Only four languages were included.",
            evidence: ["German was missing."],
          },
        },
      },
      true
    )

    expect(html).toContain('aria-label="Completion check failed"')
    expect(html).toContain("Summary: Only four languages were included.")
    expect(html).toContain("Failed")
    expect(html).toContain("German was missing.")
  })

  it("uses a compact status row while the report is running", () => {
    const html = renderPresenter({
      id: "completion-running",
      kind: "call",
      name: "report_completion",
      status: "running",
      args: {},
    })

    expect(html).toContain('aria-label="Checking completion…"')
    expect(html).toContain("Checking completion")
  })

  it("declines malformed completed payloads so the default row can render", () => {
    const row = renderCustomToolCallRow(
      presenterProps({
        id: "completion-bad",
        kind: "result",
        name: "report_completion",
        status: "completed",
        result: { status: "maybe", summary: "No verdict", evidence: [] },
      })
    )

    expect(row).toBeNull()
  })
})

function renderPresenter(activity: ToolActivity, defaultOpen = false) {
  return renderToStaticMarkup(renderCustomToolCallRow({ ...presenterProps(activity), defaultOpen }))
}

function presenterProps(activity: ToolActivity) {
  return {
    activity,
    compact: false,
    defaultOpen: false,
    live: false,
    providerKey: null,
  }
}
