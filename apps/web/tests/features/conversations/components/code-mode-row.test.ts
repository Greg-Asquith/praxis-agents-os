import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"

import { ApprovalDecisionContext } from "@/features/conversations/approval-decision-context"
import { ToolCallRow } from "@/features/conversations/components/tool-call-row"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { toolPresentationsQueryOptions } from "@/features/tools/api/list-tool-presentations"

describe("CodeModeRow", () => {
  it("keeps applied, skipped, and failed batch outcomes distinct", () => {
    const batch = {
      ...child(1),
      name: "google_ads_remove_campaign_negative_keywords",
      result: { counts: { failed: 2, not_found: 3, removed: 11 } },
    }

    const html = renderWorkflow(workflow([batch]), true)

    expect(html).toContain("Removed 11 keywords · 3 skipped · 2 failed")
  })

  it("does not claim a model-facing output before the workflow completes", () => {
    const html = renderWorkflow(workflow([], { result: null, status: "running" }), true, true)

    expect(html).not.toContain("Show output sent to model")
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
    name: "run_code",
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
      {
        effect: "write",
        label: "Apply Keyword Batch",
        name: "scenario_code_batch_write",
        provider: "test",
        ui: {
          approval_prompt: "Review every keyword before applying this batch.",
          approval_title: "Apply Keyword Batch",
          approve_label: "Approve & Apply",
          arg_fields: [
            {
              columns: [
                {
                  key: "text",
                  label: "Keyword",
                  options: [],
                  placeholder: "",
                  required: true,
                },
                {
                  key: "match_type",
                  label: "Match Type",
                  options: ["EXACT", "PHRASE", "BROAD"],
                  placeholder: "",
                  required: true,
                },
              ],
              editable: true,
              format: "records",
              key: "keywords",
              label: "Keywords",
              min_rows: 1,
              options: [],
              placeholder: "",
              secondary: false,
            },
          ],
          completed_label: "Applied Keyword Batch",
          failed_label: "Couldn’t Apply Keyword Batch",
          icon: "tool",
          result_fields: [],
          running_label: "Applying Keyword Batch…",
        },
      },
      {
        effect: "read",
        label: "Location Search Term",
        name: "classifier_location_search_term",
        provider: "classifier",
        ui: {
          approval_prompt: "The agent wants to classify these items with a helper model.",
          approval_title: "Location Search Term",
          approve_label: "Approve & Classify",
          arg_fields: [],
          completed_label: "Classified with Location Search Term",
          failed_label: "Couldn’t run Location Search Term",
          icon: "sparkles",
          result_fields: [],
          running_label: "Classifying with Location Search Term",
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
