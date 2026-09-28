import { createElement, isValidElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { ToolApprovalDecisionCard } from "@/components/tool-ui/approval-card"
import type { ToolUi, ToolUiField } from "@/features/tools/types"
import type { ToolActivity } from "@/integrations/contract"
import { airtableListRecordsPresenter } from "@/integrations/airtable/presenters/records"
import { airtableUpdateRecordPresenter } from "@/integrations/airtable/presenters/write"

const NODE = (content: string, ref = "rec-1") => ({
  node: "praxis_untrusted" as const,
  source_kind: "airtable_record",
  source_ref: ref,
  content,
})

describe("Airtable tool presenters", () => {
  it("renders listed records as defensive field tables with native untrusted content", () => {
    const html = render(
      airtableListRecordsPresenter.render(
        props({
          id: "list-1",
          kind: "result",
          name: "airtable_list_records",
          status: "completed",
          args: { table: "Projects", view: "Active", max_records: 25 },
          result: {
            results: [
              entry({
                records: [
                  record({
                    Name: NODE("Launch plan"),
                    Active: true,
                    Budget: 1250,
                    Tags: [NODE("Priority"), NODE("Client")],
                    Notes: NODE("A".repeat(520)),
                    Owner: { name: NODE("Ada"), email: NODE("ada@example.com") },
                  }),
                ],
                total: 1,
              }),
              entry(null, {
                provider_key: "airtable",
                display_name: "Archive base",
                external_id: "app-archive",
                status: "error",
                error_message: "Access needs to be renewed.",
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain("Launch plan")
    expect(html).toContain("Access needs to be renewed.")
    expect(html).not.toContain("praxis_untrusted")
    expect(html).not.toContain("PRAXIS_UNTRUSTED_CONTENT")
  })

  it("renders record write approvals through the existing controls and lists every field", () => {
    const controls = approvalControls()
    const declaredFields = [
      field("table", "Declared Table", "text", true),
      field("record_id", "Declared Record"),
      field("fields", "Declared Fields", "keyvalue", true),
    ]
    const rendered = airtableUpdateRecordPresenter.render(
      props(
        {
          id: "update-1",
          kind: "approval",
          name: "airtable_update_record",
          status: "awaiting_approval",
          args: {
            table: "Projects",
            record_id: "rec-1",
            fields: { Status: "Complete", Owner: "Ada" },
          },
        },
        controls,
        toolUi(declaredFields)
      )
    )

    expect(isValidElement(rendered)).toBe(true)
    if (isValidElement<{ controls: unknown; fields: ToolUiField[] }>(rendered)) {
      expect(rendered.type).toBe(ToolApprovalDecisionCard)
      expect(rendered.props.controls).toBe(controls)
      expect(rendered.props.fields).toBe(declaredFields)
    }
    const html = render(rendered)
    expect(html).toContain("Status")
    expect(html).toContain("Complete")
  })

  it("falls through for malformed read payloads", () => {
    expect(
      airtableListRecordsPresenter.render(
        props({
          id: "list-1",
          kind: "result",
          name: "airtable_list_records",
          status: "completed",
          result: { results: [entry({ records: "bad", total: 1 })] },
        })
      )
    ).toBeNull()
  })
})

function props(
  activity: ToolActivity,
  approvalDecision?: Parameters<typeof airtableUpdateRecordPresenter.render>[0]["approvalDecision"],
  ui?: ToolUi
) {
  return {
    activity,
    ...(approvalDecision ? { approvalDecision } : {}),
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "airtable",
    ...(ui ? { ui } : {}),
  }
}

function field(
  key: string,
  label: string,
  format: ToolUiField["format"] = "text",
  editable = false
): ToolUiField {
  return {
    key,
    label,
    format,
    editable,
    min_rows: 0,
    secondary: false,
    options: [],
    placeholder: "",
  }
}

function toolUi(argFields: ToolUiField[]): ToolUi {
  return {
    approval_prompt: "",
    approval_title: "",
    approve_label: "",
    arg_fields: argFields,
    completed_label: "",
    failed_label: "",
    icon: "airtable",
    result_fields: [],
    running_label: "",
  }
}

function entry(
  data: unknown,
  overrides: Partial<{
    provider_key: string
    display_name: string
    external_id: string
    status: string
    error_message: string | null
  }> = {}
) {
  return {
    provider_key: "airtable",
    display_name: "Projects base",
    external_id: "app-projects",
    status: "success",
    data,
    error_message: null,
    ...overrides,
  }
}

function record(fields: Record<string, unknown>) {
  return {
    record_id: "rec-1",
    created_time: "2026-07-23T09:00:00Z",
    fields,
  }
}

function approvalControls() {
  return {
    decision: { decision: "pending" as const, edits: {}, message: "" as const },
    error: null,
    onDecisionChange: vi.fn(),
    onRetry: vi.fn(),
    pendingCount: 1,
    submitting: false,
  }
}

function render(node: ReactNode) {
  return renderToStaticMarkup(createElement("div", null, node))
}
