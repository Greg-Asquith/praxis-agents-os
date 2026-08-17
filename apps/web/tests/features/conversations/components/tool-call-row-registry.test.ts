import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"

import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import type { ToolRowPresenter, ToolRowPresenterProps } from "@/integrations/contract"

const integrationToolRowPresenters = vi.hoisted(() => vi.fn())

vi.mock("@/integrations/registry", () => ({ integrationToolRowPresenters }))

afterEach(() => {
  vi.restoreAllMocks()
})

describe("renderCustomToolCallRow", () => {
  it("renders a running run_code call without exposing the full script task", () => {
    integrationToolRowPresenters.mockReturnValue([])

    const row = renderCustomToolCallRow({
      ...props(),
      activity: {
        id: "run-code-1",
        kind: "call",
        name: "run_code",
        status: "running",
        args: { task: "A very long operator-authored presentation brief" },
      },
    })
    const html = renderToStaticMarkup(row)

    expect(html).toContain("Run Script")
    expect(html).toContain("Computing and preparing any requested files…")
    expect(html).not.toContain("A very long operator-authored presentation brief")
    expect(html).toContain('aria-busy="true"')
  })

  it("renders a declared run_code edit as a new revision of the source file", () => {
    integrationToolRowPresenters.mockReturnValue([])
    const row = renderCustomToolCallRow({
      ...props(),
      defaultOpen: true,
      activity: {
        id: "run-code-edit-1",
        kind: "result",
        name: "run_code",
        status: "completed",
        result: {
          model: "claude-sonnet-5",
          model_provider: "anthropic",
          outputs: [
            {
              kind: "file",
              media_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
              name: "budget.xlsx",
              reference: {
                entity_id: "file-1",
                entity_kind: "file",
                label: "budget.xlsx",
              },
              revision_id: "revision-2",
              revision_number: 2,
              size_bytes: 8192,
              updated_existing: true,
            },
          ],
          result: "Added the totals column.",
          skipped_outputs: [],
        },
      },
    })
    const html = renderToStaticMarkup(
      createElement(QueryClientProvider, { client: new QueryClient() }, row)
    )

    expect(html).toContain("1 updated")
    expect(html).toContain("Updated")
    expect(html).toContain("Revision 2")
    expect(html).toContain("budget.xlsx")
    expect(html).not.toContain("1 created")
  })

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

  it("renders a completed classification through the native classifier presenter", () => {
    integrationToolRowPresenters.mockReturnValue([])

    const row = renderCustomToolCallRow({
      ...props(),
      defaultOpen: true,
      activity: {
        id: "classify-1",
        kind: "result",
        name: "classify",
        status: "completed",
        args: {
          items: ["Refund requested", "Great support"],
          labels: ["complaint", "praise", "other"],
        },
        result: {
          model: "gpt-5.6-luna",
          model_provider: "openai",
          results: [
            { index: 0, value: "Refund requested", label: "complaint" },
            { index: 1, value: "Great support", label: "praise" },
          ],
        },
      },
    })
    const html = renderToStaticMarkup(row)

    expect(html).toContain("Classify")
    expect(html).toContain("2 Classified")
    expect(html).toContain("Refund requested")
    expect(html).not.toContain("Ran classify")
  })

  it("renders artifact discovery through the native artifact presenter", () => {
    integrationToolRowPresenters.mockReturnValue([])

    const row = renderCustomToolCallRow({
      ...props(),
      defaultOpen: true,
      activity: {
        id: "artifacts-1",
        kind: "result",
        name: "list_artifacts",
        status: "completed",
        args: { search: "quarterly" },
        result: {
          items: [
            {
              id: "artifact-1",
              reference: {
                version: 1,
                entity_kind: "artifact",
                entity_id: "artifact-1",
                label: "Quarterly report",
                description: "Markdown artifact",
                scope_label: null,
              },
              title: "Quarterly report",
              artifact_type: "markdown",
              version_count: 2,
              updated_at: "2026-08-14T10:00:00Z",
              conversation_id: null,
            },
          ],
          total: 1,
          returned: 1,
        },
      },
    })
    const html = renderToStaticMarkup(row)

    expect(html).toContain("Artifacts")
    expect(html).toContain("Quarterly report")
    expect(html).toContain('href="/artifacts/artifact-1"')
    expect(html).not.toContain("Ran list_artifacts")
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
