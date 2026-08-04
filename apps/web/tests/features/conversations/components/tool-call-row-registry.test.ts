import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { afterEach, describe, expect, it, vi } from "vitest"

import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import type { ToolRowPresenter, ToolRowPresenterProps } from "@/integrations/contract"

const integrationToolRowPresenters = vi.hoisted(() => vi.fn())

vi.mock("@/integrations/registry", () => ({ integrationToolRowPresenters }))

afterEach(() => {
  vi.restoreAllMocks()
})

describe("renderCustomToolCallRow", () => {
  it("renders a running Fetch URL call through the native web presenter", () => {
    integrationToolRowPresenters.mockReturnValue([])

    const row = renderCustomToolCallRow({
      ...props(),
      activity: {
        id: "fetch-1",
        kind: "call",
        name: "fetch_url",
        status: "running",
        args: { url: "https://docs.example.com/page" },
      },
    })
    const html = renderToStaticMarkup(row)

    expect(html).toContain("Web Fetch")
    expect(html).toContain("Fetching https://docs.example.com/page…")
    expect(html).toContain('aria-busy="true"')
  })

  it("renders a completed Fetch URL result through the native web presenter", () => {
    integrationToolRowPresenters.mockReturnValue([])

    const row = renderCustomToolCallRow({
      ...props(),
      defaultOpen: true,
      activity: {
        id: "fetch-1",
        kind: "result",
        name: "fetch_url",
        status: "completed",
        result: {
          content: {
            node: "praxis_untrusted",
            source_kind: "web_fetch",
            source_ref: "https://docs.example.com/page",
            content: "# Praxis documentation",
          },
          model: "claude-sonnet-5",
          model_provider: "anthropic",
          sources: [{ title: "Praxis docs", url: "https://docs.example.com/page" }],
          url: "https://docs.example.com/page",
        },
      },
    })
    const html = renderToStaticMarkup(row)

    expect(html).toContain("Web Fetch")
    expect(html).toContain("Fetched Page Content")
    expect(html).toContain("Praxis docs")
  })

  it("renders a completed Build Chart result through the native chart presenter", () => {
    integrationToolRowPresenters.mockReturnValue([])

    const row = renderCustomToolCallRow({
      ...props(),
      activity: {
        id: "chart-1",
        kind: "result",
        name: "build_chart",
        status: "completed",
        args: chartArgs(),
        result: { title: "Revenue by region", points: 1, series: 1 },
      },
    })
    const html = renderToStaticMarkup(row)

    expect(html).toContain("Build Chart")
    expect(html).toContain("Revenue by region")
    expect(html).toContain("Loading chart…")
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

function chartArgs() {
  return {
    chart_type: "bar",
    title: "Revenue by region",
    x_axis: {
      data_key: "region",
    },
    series: [
      {
        data_key: "revenue",
        label: "Revenue",
        format: "currency",
        currency_code: "GBP",
      },
    ],
    data: [{ region: "North", revenue: 1250 }],
  }
}
