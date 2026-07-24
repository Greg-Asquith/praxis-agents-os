import { createElement, isValidElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { ToolApprovalDecisionCard } from "@/components/tool-ui/approval-card"
import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import type { ToolActivity } from "@/integrations/contract"
import airtableModule from "@/integrations/airtable"
import {
  airtableGetRecordPresenter,
  airtableListRecordsPresenter,
} from "@/integrations/airtable/presenters/records"
import {
  airtableCreateRecordPresenter,
  airtableUpdateRecordPresenter,
} from "@/integrations/airtable/presenters/write"
import { integrationToolRowPresenters, loadIntegrationUiModules } from "@/integrations/registry"

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
                connection_id: "connection-2",
                display_name: "Archive base",
                external_id: "app-archive",
                status: "failed",
                error_message: "Access needs to be renewed.",
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain("List Airtable Records")
    expect(html).toContain("Projects")
    expect(html).toContain("Active")
    expect(html).toContain("Launch plan")
    expect(html).toContain("Budget")
    expect(html).toContain("1250")
    expect(html).toContain("Priority")
    expect(html).toContain("Client")
    expect(html).toContain("Show Full Content")
    expect(html).toContain("ada@example.com")
    expect(html).toContain("Access needs to be renewed.")
    expect(html).not.toContain("praxis_untrusted")
    expect(html).not.toContain("PRAXIS_UNTRUSTED_CONTENT")
  })

  it("renders a single record and honest read loading states", () => {
    const html = render(
      airtableGetRecordPresenter.render(
        props({
          id: "get-1",
          kind: "result",
          name: "airtable_get_record",
          status: "completed",
          args: { table: "Projects", record_id: "rec-1" },
          result: { results: [entry(record({ Name: NODE("Launch plan") }))] },
        })
      )
    )
    expect(html).toContain("Get Airtable Record")
    expect(html).toContain("rec-1")
    expect(html).toContain("Launch plan")

    expect(
      render(
        airtableListRecordsPresenter.render(
          props({
            id: "list-1",
            kind: "call",
            name: "airtable_list_records",
            status: "running",
          })
        )
      )
    ).toContain("Loading Airtable records…")
    expect(
      render(
        airtableGetRecordPresenter.render(
          props({
            id: "get-1",
            kind: "call",
            name: "airtable_get_record",
            status: "running",
          })
        )
      )
    ).toContain("Loading Airtable record…")
  })

  it("renders record write approvals through the existing controls and lists every field", () => {
    const controls = approvalControls()
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
        controls
      )
    )

    expect(isValidElement(rendered)).toBe(true)
    if (isValidElement<{ controls: unknown }>(rendered)) {
      expect(rendered.type).toBe(ToolApprovalDecisionCard)
      expect(rendered.props.controls).toBe(controls)
    }
    const html = render(rendered)
    expect(html).toContain("Review Airtable record update")
    expect(html).toContain("Projects")
    expect(html).toContain("rec-1")
    expect(html).toContain("Fields to write")
    expect(html).toContain("Status")
    expect(html).toContain("Complete")
    expect(html).toContain("Owner")
    expect(html).toContain("Ada")
    expect(html).toContain("Approve &amp; Update")
    expect(html).toContain("Decline")
  })

  it.each([
    [
      airtableCreateRecordPresenter,
      "airtable_create_record",
      "running",
      "Creating Airtable record…",
    ],
    [
      airtableCreateRecordPresenter,
      "airtable_create_record",
      "awaiting_approval",
      "Waiting for record creation approval…",
    ],
    [airtableCreateRecordPresenter, "airtable_create_record", "denied", "Nothing was changed."],
    [
      airtableCreateRecordPresenter,
      "airtable_create_record",
      "failed",
      "No Airtable change was confirmed.",
    ],
    [
      airtableCreateRecordPresenter,
      "airtable_create_record",
      "unknown",
      "No Airtable change was confirmed.",
    ],
    [
      airtableUpdateRecordPresenter,
      "airtable_update_record",
      "running",
      "Updating Airtable record…",
    ],
    [
      airtableUpdateRecordPresenter,
      "airtable_update_record",
      "awaiting_approval",
      "Waiting for record update approval…",
    ],
    [airtableUpdateRecordPresenter, "airtable_update_record", "denied", "Nothing was changed."],
    [
      airtableUpdateRecordPresenter,
      "airtable_update_record",
      "failed",
      "No Airtable change was confirmed.",
    ],
    [
      airtableUpdateRecordPresenter,
      "airtable_update_record",
      "unknown",
      "No Airtable change was confirmed.",
    ],
  ] as const)("renders an honest %s %s lifecycle state", (presenter, name, status, expected) => {
    const html = render(
      presenter.render(
        props({
          id: `${name}-${status}`,
          kind: "call",
          name,
          status,
          args: {
            table: "Projects",
            ...(name === "airtable_update_record" ? { record_id: "rec-1" } : {}),
            fields: { Status: "Complete" },
          },
        })
      )
    )
    expect(html).toContain(expected)
  })

  it("renders confirmed create and update receipts with their Airtable record ids", () => {
    for (const [presenter, name, recordId] of [
      [airtableCreateRecordPresenter, "airtable_create_record", "rec-created"],
      [airtableUpdateRecordPresenter, "airtable_update_record", "rec-updated"],
    ] as const) {
      const html = render(
        presenter.render(
          props({
            id: name,
            kind: "result",
            name,
            status: "completed",
            args: {
              table: "Projects",
              ...(name === "airtable_update_record" ? { record_id: "rec-1" } : {}),
              fields: { Status: "Complete" },
            },
            result: { results: [entry({ record_id: recordId })] },
          })
        )
      )
      expect(html).toContain(recordId)
      expect(html).toContain(
        name === "airtable_create_record" ? "Record created" : "Record updated"
      )
    }
  })

  it("falls through for malformed read payloads and registers all presenters", () => {
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
    expect(airtableModule.toolRowPresenters.map((presenter) => presenter.key)).toEqual([
      "airtable-list-records",
      "airtable-get-record",
      "airtable-create-record",
      "airtable-update-record",
    ])
    expect(airtableCreateRecordPresenter.handlesApprovals).toBe(true)
    expect(airtableUpdateRecordPresenter.handlesApprovals).toBe(true)
  })

  it("loads and renders Airtable records through the production registry seam", async () => {
    await loadIntegrationUiModules(["airtable"])

    expect(integrationToolRowPresenters("airtable").map((presenter) => presenter.key)).toContain(
      "airtable-list-records"
    )
    const row = renderCustomToolCallRow(
      props({
        id: "list-registry-1",
        kind: "result",
        name: "airtable_list_records",
        status: "completed",
        result: {
          results: [entry({ records: [record({ Name: NODE("Launch plan") })], total: 1 })],
        },
      })
    )
    const html = render(row)
    expect(html).toContain('aria-label="Airtable record results"')
    expect(html).toContain("Launch plan")
  })
})

function props(
  activity: ToolActivity,
  approvalDecision?: Parameters<typeof airtableUpdateRecordPresenter.render>[0]["approvalDecision"]
) {
  return {
    activity,
    ...(approvalDecision ? { approvalDecision } : {}),
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "airtable",
  }
}

function entry(
  data: unknown,
  overrides: Partial<{
    connection_id: string
    display_name: string
    external_id: string
    status: string
    error_message: string | null
  }> = {}
) {
  return {
    connection_id: "connection-1",
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
