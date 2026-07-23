import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import type { ToolActivity } from "@/features/conversations/message-parts"

describe("todo tool presenter", () => {
  it("renders write_todos as a dedicated plan card with progress and step states", () => {
    const html = renderPresenter({
      id: "write-1",
      kind: "result",
      name: "write_todos",
      status: "completed",
      result: {
        items: [
          { content: "Collect context", status: "completed" },
          { content: "Draft the change", status: "in_progress" },
          { content: "Run checks", status: "pending" },
        ],
      },
    })

    expect(html).toContain('data-slot="plan-card"')
    expect(html).toContain('aria-label="Plan, 1 of 3 done"')
    expect(html).toContain("Now: Draft the change")
    expect(html).toContain("In progress")
    expect(html).toContain("line-through")
    expect(html).not.toContain('data-slot="tool-field-well"')
    expect(html).not.toContain("<details")
  })

  it("keeps read_todos as a compact lookup row", () => {
    const html = renderPresenter({
      id: "read-1",
      kind: "result",
      name: "read_todos",
      status: "completed",
      result: {
        items: [
          { content: "Collect context", status: "completed" },
          { content: "Draft the change", status: "pending" },
        ],
      },
    })

    expect(html).toContain('aria-label="Plan lookup"')
    expect(html).toContain("Checked the plan")
    expect(html).toContain("1 of 2 done")
    expect(html).not.toContain('data-slot="plan-card"')
    expect(html).not.toContain("Collect context")
  })

  it("keeps a running read_todos lookup compact before its result arrives", () => {
    const html = renderPresenter({
      id: "read-running",
      kind: "call",
      name: "read_todos",
      status: "running",
      args: {},
    })

    expect(html).toContain('aria-label="Plan lookup"')
    expect(html).toContain("Checking the plan")
    expect(html).not.toContain('data-slot="plan-card"')
  })

  it("declines malformed payloads so the default tool row can render", () => {
    const row = renderCustomToolCallRow(
      presenterProps({
        id: "write-bad",
        kind: "result",
        name: "write_todos",
        status: "completed",
        args: { items: [{ content: "Original", status: "pending" }] },
        result: { items: [{ content: "", status: "unknown" }] },
      })
    )

    expect(row).toBeNull()
  })
})

function renderPresenter(activity: ToolActivity) {
  return renderToStaticMarkup(renderCustomToolCallRow(presenterProps(activity)))
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
