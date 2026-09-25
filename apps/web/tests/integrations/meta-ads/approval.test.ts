import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import type { ApprovalField } from "@/components/tool-ui/approval-types"
import type { EditedValues } from "@/components/tool-ui/edited-values"
import { buildResumeDecisions } from "@/features/conversations/approval-decisions"
import { MetaAdsInsightsApproval } from "@/integrations/meta_ads/components/insights-approval"
import {
  insightsApprovalError,
  parseInsightsApproval,
} from "@/integrations/meta_ads/lib/insights-approval"
import { metaAdsInsightsPresenter } from "@/integrations/meta_ads/presenters/insights"

import formSchema from "./insights-form-schema.json"
import { parseInsightsOptions } from "@/integrations/meta_ads/lib/insights-options"

const options = parseInsightsOptions(formSchema)
if (!options) throw new Error("Invalid backend form schema fixture")

const args = {
  fields: ["campaign_name", "campaign_id", "spend"],
  since: "2026-01-01",
  until: "2026-09-24",
}
const field = (key: string, format: ApprovalField["format"] = "text"): ApprovalField => ({
  key,
  label: key,
  format,
  editable: true,
  secondary: true,
  min_rows: 0,
  options: [],
  placeholder: "",
})
const fields: ApprovalField[] = [
  field("since"),
  field("until"),
  field("fields", "list"),
  { ...field("level"), options: ["account", "campaign", "adset", "ad"] },
  field("limit", "number"),
  field("sort"),
  field("breakdowns", "list"),
  field("action_breakdowns", "list"),
  field("attribution_windows", "list"),
  { ...field("time_increment"), options: ["all_days", "monthly", "1", "7"] },
  {
    ...field("filters", "records"),
    columns: [
      { key: "field", label: "Field", options: [], placeholder: "", required: true },
      { key: "operator", label: "Operator", options: [], placeholder: "", required: true },
      {
        key: "value",
        label: "Value",
        format: "scalar_or_list",
        options: [],
        placeholder: "",
        required: true,
      },
    ],
  },
]

function render(
  overrides: Record<string, unknown> = {},
  edits: EditedValues = {},
  schema: unknown = formSchema
) {
  return renderToStaticMarkup(
    createElement(MetaAdsInsightsApproval, {
      formSchema: schema,
      activity: {
        id: "report",
        name: "meta_ads_run_insights",
        kind: "approval",
        status: "awaiting_approval",
        args: { ...args, ...overrides },
      },
      controls: {
        decision: { decision: "pending", edits, message: "" },
        disabled: false,
        error: null,
        onDecisionChange: () => undefined,
        onRetry: () => undefined,
        pendingCount: 1,
        submitting: false,
      },
    })
  )
}

function resume(original: Record<string, unknown>, edits: EditedValues) {
  return buildResumeDecisions(
    [{ tool_call_id: "report", name: "meta_ads_run_insights", args: original }],
    { report: { decision: "approved", edits, message: "" } },
    () => fields
  )
}

describe("Meta Insights approval", () => {
  it.each([{}, { filters: null }, { filters: [] }])(
    "enables approval without optional filters: %j",
    (optional) => {
      const html = render(optional)
      expect(metaAdsInsightsPresenter.handlesApprovals).toBe(true)
      expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>Approve<\/button>/)
      expect(html).toContain(">Approve</button>")
      expect(html.match(/type="date"/g)).toHaveLength(2)
      expect(html).toContain("Search Report fields")
      expect(html).toContain("Advanced options")
      expect(html).toContain("Maximum rows")
      expect(html).toContain("Report interval")
      expect(html).toContain("Add filter")
      expect(html).not.toContain("Other Options")
    }
  )

  it.each([undefined, null, {}, { properties: {} }])(
    "blocks approval with a visible recovery message when metadata is unavailable: %j",
    (schema) => {
      const html = render({}, {}, schema ?? null)
      expect(html).toContain("Report options are unavailable.")
      expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Approve<\/button>/)
      expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>Decline<\/button>/)
    }
  )

  it("uses backend defaults, choices, and bounds without frontend fallbacks", () => {
    const changed = structuredClone(formSchema)
    changed.properties.level.enum = ["account", "new_level"]
    changed.properties.level.default = "new_level"
    changed.properties.limit.default = 25
    changed.properties.limit.maximum = 50
    changed.properties.time_increment.default = "weekly"
    const intervalChoices = changed.properties.time_increment.anyOf.find((item) => item.enum)
    if (!intervalChoices) throw new Error("Missing interval choices")
    intervalChoices.enum = ["weekly"]
    changed.properties.fields.items.examples = ["backend_metric"]
    changed.properties.breakdowns.items.enum = ["backend_breakdown"]
    const received = parseInsightsOptions(changed)
    expect(received).not.toBeNull()
    if (!received) throw new Error("Invalid modified form schema")
    const parsed = parseInsightsApproval(args, received)
    expect(parsed).toMatchObject({ level: "new_level", limit: 25, time_increment: "weekly" })
    expect(received.fields.values).toEqual(["backend_metric"])
    expect(
      insightsApprovalError(
        parseInsightsApproval({ ...args, breakdowns: ["backend_breakdown"] }, received),
        received
      )
    ).toBeNull()
    expect(
      insightsApprovalError(
        parseInsightsApproval({ ...args, level: "campaign" }, received),
        received
      )
    ).not.toBeNull()
    expect(
      insightsApprovalError(parseInsightsApproval({ ...args, limit: 51 }, received), received)
    ).toContain("50")
    const html = render({}, {}, changed)
    expect(html).toContain('max="50"')
    expect(html).toContain('value="25"')
    expect(html).toContain("New Level")
  })

  it("shows a reason for invalid dates and blocks approval", () => {
    const html = render({}, { until: "2025-12-31" })
    expect(html).toContain("The end date must be on or after the start date.")
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Approve<\/button>/)
  })

  it("submits every editable option when omitted from the original request", () => {
    const edits: EditedValues = {
      level: "adset",
      since: "2026-02-01",
      fields: ["spend", "actions"],
      limit: 500,
      sort: "spend_descending",
      time_increment: 7,
      breakdowns: ["country"],
      action_breakdowns: ["action_type"],
      attribution_windows: ["7d_click"],
      filters: [
        { field: "campaign.id", operator: "IN", value: ["123", "456"] },
        { field: "spend", operator: "GREATER_THAN", value: 5 },
      ],
    }
    expect(resume(args, edits)).toEqual([
      { tool_call_id: "report", decision: "approved", override_args: { ...args, ...edits } },
    ])
    expect(
      insightsApprovalError(parseInsightsApproval({ ...args, ...edits }, options), options)
    ).toBeNull()
  })

  it("preserves numeric filter lists and switches numeric intervals back to monthly", () => {
    const original = { ...args, filters: null, time_increment: 7 }
    const edits = {
      filters: [{ field: "spend", operator: "IN", value: [1, 2] }],
      time_increment: "monthly",
    }
    expect(resume(original, edits)).toEqual([
      { tool_call_id: "report", decision: "approved", override_args: { ...original, ...edits } },
    ])
  })

  it("clears explicit attribution to restore ad set settings", () => {
    const original = { ...args, attribution_windows: ["1d_click"] }
    expect(resume(original, { attribution_windows: null })).toEqual([
      {
        tool_call_id: "report",
        decision: "approved",
        override_args: { ...original, attribution_windows: null },
      },
    ])
  })

  it.each([
    { since: "2026-02-30" },
    { fields: [] },
    { limit: 0 },
    { limit: 1001 },
    { time_increment: 91 },
    { breakdowns: ["unsupported"] },
    { filters: [{ field: "spend", operator: "IN", value: [] }] },
    { filters: [{ field: "spend", operator: "GREATER_THAN", value: "five" }] },
  ])("rejects invalid report edits: %j", (overrides) => {
    expect(
      insightsApprovalError(parseInsightsApproval({ ...args, ...overrides }, options), options)
    ).not.toBeNull()
  })
})
