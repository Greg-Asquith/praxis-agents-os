import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"

import { ApprovalDecisionContext } from "@/features/conversations/approval-decision-context"
import { ToolCallRow } from "@/features/conversations/components/tool-call-row"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { toolPresentationsQueryOptions } from "@/features/tools/api/list-tool-presentations"
import { loadIntegrationUiModules } from "@/integrations/registry"

describe("CodeModeRow", () => {
  it("renders a compact running state before the first tool call arrives", () => {
    const html = renderWorkflow(workflow([], { status: "running" }), false, true)

    expect(html).toContain("Running workflow…")
    expect(html).toContain('aria-busy="true"')
  })

  it("keeps the script behind a disclosure and recurses through standard tool rows", () => {
    const html = renderWorkflow(workflow([child(1)]), true)

    expect(html).toContain("Completed with 1 tool call")
    expect(html).toContain("Checked item")
    expect(html).toContain("Show script")
    expect(html).toContain("await read_file")
  })

  it("shows the exact final workflow output sent to the model", () => {
    const html = renderWorkflow(
      workflow([child(1)], {
        result: { accounts: 2, rows: 94, status: "aggregated" },
      }),
      true
    )

    expect(html).toContain("Show output sent to model")
    expect(html).toContain("&quot;accounts&quot;: 2")
    expect(html).toContain("&quot;rows&quot;: 94")
    expect(html).toContain("&quot;status&quot;: &quot;aggregated&quot;")
  })

  it("does not claim a model-facing output before the workflow completes", () => {
    const html = renderWorkflow(workflow([], { result: null, status: "running" }), true, true)

    expect(html).not.toContain("Show output sent to model")
  })

  it("shows persisted trace excerpts when structured presenter fields are unavailable", () => {
    const traceChild = {
      ...child(1),
      result: '{"results":[]}',
      resultExcerpt: '{"results":[]}',
    }
    const html = renderWorkflow(workflow([traceChild]), true)

    expect(html).toContain("Recorded result")
    expect(html).toContain("{&quot;results&quot;:[]}")
  })

  it("does not render malformed JSON when a legacy trace excerpt was truncated", () => {
    const traceChild = {
      ...child(1),
      result: '{"results":[{"data":…[excerpt truncated]…"status":"success"}]}',
      resultExcerpt: '{"results":[{"data":…[excerpt truncated]…"status":"success"}]}',
    }
    const html = renderWorkflow(workflow([traceChild]), true)

    expect(html).toContain("Detailed result preview was truncated")
    expect(html).not.toContain("&quot;results&quot;")
  })

  it("renders a retained Google Ads report with its normal table presenter", async () => {
    await loadIntegrationUiModules(["google_ads"])
    const report: ToolActivity = {
      id: "workflow-1:1",
      kind: "result",
      name: "google_ads_run_report",
      status: "completed",
      resultExcerpt: '{"results":[…[excerpt truncated]…]}',
      result: {
        results: [
          {
            connection_id: "connection-1",
            data: {
              currency_code: "GBP",
              row_count: 1,
              rows: [{ metrics: { clicks: "3", impressions: "10" } }],
              truncated: false,
              truncation_note: null,
            },
            display_name: "Search account",
            error_code: null,
            error_message: null,
            external_id: "1234567890",
            status: "success",
          },
        ],
      },
    }

    const html = renderWorkflow(workflow([report]), true)

    expect(html).toContain('aria-label="Google Ads report results"')
    expect(html).toContain("Search account")
    expect(html).toContain("123-456-7890")
    expect(html).not.toContain("Recorded result")
  })

  it("bounds the supported 25-call workflow with stable intrinsic row sizing", () => {
    const html = renderWorkflow(
      workflow(Array.from({ length: 25 }, (_, index) => child(index + 1))),
      true
    )

    expect(html).toContain("Show all 25 tool calls")
    expect(html.match(/content-visibility:auto/g)).toHaveLength(12)
    expect(html.match(/contain-intrinsic-size:auto_3rem/g)).toHaveLength(12)
  })

  it("renders a malformed 100-call legacy trace without mounting every child", () => {
    const html = renderWorkflow(
      workflow(Array.from({ length: 100 }, (_, index) => child(index + 1))),
      true
    )

    expect(html).toContain("Show all 100 tool calls")
    expect(html.match(/content-visibility:auto/g)).toHaveLength(12)
    expect(html).not.toContain("Result 100")
  })

  it("auto-expands and includes a pending approval beyond the disclosure cap", () => {
    const children = Array.from({ length: 25 }, (_, index) => child(index + 1))
    children[24] = child(25, "awaiting_approval")
    const html = renderWorkflow(workflow(children), false, false, "workflow-1:25")

    expect(html).toContain("Review needed")
    expect(html).toContain('aria-expanded="true"')
    expect(html).toContain("Approval request: Check item")
    expect(html).toContain("Show all 25 tool calls")
    expect(html.match(/content-visibility:auto/g)).toHaveLength(13)
  })

  it("summarizes a paused workflow as waiting for review, never completed", () => {
    const html = renderWorkflow(
      workflow([child(1), child(2, "awaiting_approval")]),
      false,
      false,
      "workflow-1:2"
    )

    expect(html).toContain("Waiting for your review")
    expect(html).not.toContain("Completed with")
  })

  it("warns when a pending workflow action was derived from untrusted data", () => {
    const pending = child(1, "awaiting_approval")
    pending.derivedFromUntrusted = true
    pending.taintSources = [{ source_kind: "gmail_message", source_ref: "message-1" }]

    const html = renderWorkflow(workflow([pending]), false, false, pending.id)

    expect(html).toContain("Based on external data")
    expect(html).toContain("message-1")
    expect(html).toContain("file-1")
  })
})

function workflow(children: ToolActivity[], overrides: Partial<ToolActivity> = {}): ToolActivity {
  return {
    id: "workflow-1",
    kind: "call",
    name: "run_workflow",
    status: "completed",
    result: "done",
    script: {
      children,
      code: "result = await read_file(file_id='file-1')\nresult",
      error: null,
      output: null,
      reason: null,
      status: overrides.status ?? "completed",
    },
    ...overrides,
  }
}

function child(index: number, status: ToolActivity["status"] = "completed"): ToolActivity {
  return {
    id: `workflow-1:${String(index)}`,
    kind: status === "awaiting_approval" ? "approval" : "result",
    name: "check_item",
    status,
    args: { file_id: `file-${String(index)}` },
    result: status === "completed" ? `Result ${String(index)}` : null,
  }
}

function renderWorkflow(
  activity: ToolActivity,
  defaultOpen = false,
  live = false,
  pendingApprovalId: string | null = null
) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(toolPresentationsQueryOptions().queryKey, {
    tools: [
      {
        effect: "read",
        label: "Check item",
        name: "check_item",
        provider: "core",
        ui: {
          approval_prompt: "The agent wants to check this item.",
          approval_title: "Check item",
          approve_label: "Approve",
          arg_fields: [],
          completed_label: "Checked item",
          failed_label: "Couldn’t check item",
          icon: "tool",
          result_fields: [],
          running_label: "Checking item…",
        },
      },
    ],
  })
  const resolveApproval = (candidate: ToolActivity) =>
    candidate.id === pendingApprovalId
      ? {
          decision: { decision: "pending" as const, edits: {}, message: "" as const },
          disabled: false,
          error: null,
          onDecisionChange: vi.fn(),
          onRetry: vi.fn(),
          pendingCount: 1,
          submitting: false,
        }
      : null

  return renderToStaticMarkup(
    createElement(QueryClientProvider, {
      client: queryClient,
      children: createElement(ApprovalDecisionContext, {
        value: resolveApproval,
        children: createElement(ToolCallRow, { activity, defaultOpen, live }),
      }),
    })
  )
}
