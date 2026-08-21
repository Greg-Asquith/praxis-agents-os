import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { afterEach, describe, expect, it, vi } from "vitest"

import {
  TOOL_ROW_PRESENTERS,
  renderCustomToolCallRow,
} from "@/features/conversations/components/tool-call-row-registry"
import type { ToolRowPresenter, ToolRowPresenterProps } from "@/integrations/contract"

const integrationToolRowPresenters = vi.hoisted(() => vi.fn())

vi.mock("@/integrations/registry", () => ({ integrationToolRowPresenters }))

afterEach(() => {
  vi.restoreAllMocks()
})

describe("renderCustomToolCallRow", () => {
  it("keeps native presenter precedence explicit", () => {
    expect(TOOL_ROW_PRESENTERS.map((presenter) => presenter.key)).toEqual([
      "run-code",
      "code-mode-workflow",
      "completion-report",
      "artifact-tools",
      "classifier",
      "build-chart",
      "web-fetch",
      "web-search",
      "delegate-agent-list",
      "delegation",
      "skill-activation",
      "skill-document-read",
      "todo-plan",
      "todo-lookup",
      "file-tools",
      "kb-tools",
      "memory-tools",
    ])
  })

  it("does not let a matching presenter replace the default approval row without opting in", () => {
    const render = vi.fn(() => createElement("p", null, "Custom presenter"))
    integrationToolRowPresenters.mockReturnValue([
      {
        key: "details",
        matches: () => true,
        render,
      },
    ] satisfies ToolRowPresenter[])

    const row = renderCustomToolCallRow({
      ...props(),
      approvalDecision: approvalDecision(),
    })

    expect(row).toBeNull()
    expect(render).not.toHaveBeenCalled()
  })

  it("lets a presenter that handles approvals render the decision controls", () => {
    integrationToolRowPresenters.mockReturnValue([
      {
        handlesApprovals: true,
        key: "approval",
        matches: () => true,
        render: () => createElement("p", null, "Custom approval"),
      },
    ] satisfies ToolRowPresenter[])

    const row = renderCustomToolCallRow({
      ...props(),
      approvalDecision: approvalDecision(),
    })

    expect(renderToStaticMarkup(row)).toContain("Custom approval")
  })

  it("reports a broken matcher and continues to the next presenter", () => {
    const error = new Error("broken matcher")
    const presenters: ToolRowPresenter[] = [
      {
        key: "broken",
        matches: () => {
          throw error
        },
        render: () => null,
      },
      {
        key: "working",
        matches: () => true,
        render: () => createElement("p", null, "Recovered presenter"),
      },
    ]
    integrationToolRowPresenters.mockReturnValue(presenters)
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined)

    const row = renderCustomToolCallRow(props())

    expect(renderToStaticMarkup(row)).toContain("Recovered presenter")
    expect(consoleError).toHaveBeenCalledWith(
      "Tool row presenter 'broken' failed for tool 'example_tool'.",
      error
    )
  })
})

function props(): ToolRowPresenterProps {
  return {
    activity: {
      id: "tool-1",
      kind: "result",
      name: "example_tool",
      status: "completed",
    },
    compact: false,
    defaultOpen: false,
    label: "Example Tool",
    live: false,
    providerKey: "example",
    ui: null,
  }
}

function approvalDecision(): NonNullable<ToolRowPresenterProps["approvalDecision"]> {
  return {
    decision: { decision: "pending", edits: {}, message: "" },
    error: null,
    onDecisionChange: () => undefined,
    onRetry: () => undefined,
    pendingCount: 1,
    submitting: false,
  }
}
