import { createElement, isValidElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { ToolApprovalDecisionCard } from "@/components/tool-ui/approval-card"
import type { EditedRecords } from "@/components/tool-ui/edited-values"
import {
  addRecordRow,
  removeRecordRow,
  updateRecordCell,
} from "@/components/tool-ui/records-field-values"
import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import type { ToolUi, ToolUiField } from "@/features/tools/types"
import type { ToolActivity } from "@/integrations/contract"
import { googleAdsCampaignLinksPresenter } from "@/integrations/google_ads/presenters/campaign-links"
import { googleAdsCampaignStatusPresenter } from "@/integrations/google_ads/presenters/campaign-status"
import { googleAdsCreateLabelsPresenter } from "@/integrations/google_ads/presenters/create-labels"
import { googleAdsDeviceBidModifiersPresenter } from "@/integrations/google_ads/presenters/device-bid-modifiers"
import { googleAdsNegativeKeywordListsPresenter } from "@/integrations/google_ads/presenters/negative-keyword-lists"
import { googleAdsCampaignNegativeKeywordsPresenter } from "@/integrations/google_ads/presenters/negative-keywords/campaign"
import { googleAdsListNegativeKeywordsPresenter } from "@/integrations/google_ads/presenters/negative-keywords/list"
import { googleAdsReportPresenter } from "@/integrations/google_ads/presenters/report"
import { loadIntegrationUiModules } from "@/integrations/registry"

describe("Google Ads tool presenters", () => {
  it("renders a compact, exportable report table with clean headers and raw values", () => {
    const html = render(
      googleAdsReportPresenter.render(
        props({
          id: "report-1",
          kind: "result",
          name: "google_ads_run_report",
          status: "completed",
          args: { query: "SELECT campaign.id, metrics.cost_micros FROM campaign" },
          result: {
            results: [
              entry({
                currency_code: "GBP",
                rows: [
                  {
                    campaign: {
                      id: "987654",
                      resource_name: "customers/1234567890/campaigns/987654",
                      status: "ENABLED",
                    },
                    metrics: {
                      costMicros: "1250000",
                      averageCpc: "73040000",
                      costPerConversion: "51050000",
                      conversionRate: "0.25",
                      ctr: "0.125",
                      clicks: "5",
                    },
                    segments: { date: "2026-07-23" },
                  },
                ],
                row_count: 1,
                truncated: true,
                truncation_note: "Report limited to 1 row.",
              }),
            ],
          },
        })
      )
    )

    expect(html).toMatch(/£1\.25|GBP\s*1\.25/)
    expect(html).toContain("12.5%")
    expect(html).toContain("£73.04")
    expect(html).not.toContain(">Metrics Cost Micros<")
    expect(html).not.toContain("praxis_untrusted")
    expect(html).not.toContain("PRAXIS_UNTRUSTED_CONTENT")
  })

  it("blocks approval for legacy raw campaign ids", () => {
    const html = render(
      googleAdsCampaignStatusPresenter.render(
        props(
          {
            id: "campaign-legacy",
            kind: "approval",
            name: "google_ads_update_campaign_status",
            status: "awaiting_approval",
            args: { campaign_ids: ["10", "20"], status: "PAUSED" },
          },
          approvalControls(),
          toolUi([])
        )
      )
    )

    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Approve &amp; Update<\/button>/)
    expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>Decline<\/button>/)
  })

  it.each([
    {
      presenter: googleAdsCampaignStatusPresenter,
      name: "google_ads_update_campaign_status",
      key: "campaigns",
      row: { campaign_id: "10", outcome: "updated" },
      label: "10",
    },
    {
      presenter: googleAdsNegativeKeywordListsPresenter,
      name: "google_ads_create_negative_keyword_list",
      key: "outcomes",
      row: { name: "Brand exclusions", outcome: "created" },
      label: "Brand exclusions",
    },
    {
      presenter: googleAdsCreateLabelsPresenter,
      name: "google_ads_create_labels",
      key: "labels",
      row: {
        name: "Black Friday",
        background_color: "#E8710A",
        outcome: "created",
        reference: { entity_kind: "google_ads_label", customer_id: "111", label_id: "8" },
      },
      label: "Black Friday",
    },
  ])("renders and guards the $column result table", ({ presenter, name, key, row, label }) => {
    const resultHtml = (rows: unknown[]) =>
      render(
        presenter.render(
          props({
            id: "list-result",
            kind: "result",
            name,
            status: "completed",
            result: { results: [entry({ [key]: rows })] },
          })
        )
      )
    const html = resultHtml([row])
    expect(html).toContain(label)
    for (const rows of [[{ ...row, outcome: "unknown" }], [row, row], [null]]) {
      expect(resultHtml(rows)).toContain("couldn&#x27;t confirm the")
    }
  })

  it.each([
    {
      adjustments: [{ device: "MOBILE", bid_modifier: 0.05 }],
      error: "Set each bid modifier to 0 or between 0.1 and 10 before approving.",
    },
    {
      adjustments: [
        { device: "MOBILE", bid_modifier: 0.7 },
        { device: "MOBILE", bid_modifier: 0.8 },
      ],
      error: "Choose each device only once before approving.",
    },
  ])("blocks invalid edited device adjustments: $error", ({ adjustments, error }) => {
    const controls = approvalControls()
    controls.decision.edits = { adjustments }
    const html = render(
      googleAdsDeviceBidModifiersPresenter.render(
        props(
          {
            id: "device-bids-invalid-approval",
            kind: "approval",
            name: "google_ads_update_device_bid_modifiers",
            status: "awaiting_approval",
            args: {
              campaign_ids: [campaignReference("10", "Summer Sale")],
              adjustments: [{ device: "DESKTOP", bid_modifier: 1.2 }],
            },
          },
          controls,
          toolUi(deviceBidModifierFields())
        )
      )
    )

    expect(html).toContain(error)
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Approve &amp; Update<\/button>/)
    expect(html).not.toContain("Raise by 20% (1.2×)")
  })

  it.each([
    ["previous_bid_modifier", "0.7"],
    ["previous_bid_modifier", Number.NaN],
    ["external_ref", 123],
  ])("rejects malformed nullable device field %s", (key, value) => {
    const html = render(
      googleAdsDeviceBidModifiersPresenter.render(
        props({
          id: "invalid-device",
          kind: "result",
          name: "google_ads_update_device_bid_modifiers",
          status: "completed",
          result: {
            results: [
              entry({
                campaigns: [
                  {
                    campaign_id: "10",
                    campaign_name: "Brand",
                    bidding_strategy_type: "MANUAL_CPC",
                    target_cpa_configured: false,
                    devices: [
                      {
                        device: "MOBILE",
                        requested_bid_modifier: 0.7,
                        outcome: "updated",
                        external_ref: "customers/123/campaignCriteria/10~1",
                        [key]: value,
                      },
                    ],
                  },
                ],
              }),
            ],
          },
        })
      )
    )
    expect(html).toContain("couldn&#x27;t confirm the device bid adjustments outcome")
  })

  it("keeps valid keyword outcomes when a provider failure has no operation index", () => {
    const html = render(
      googleAdsListNegativeKeywordsPresenter.render(
        props({
          id: "negative-keywords-unattributed-error",
          kind: "result",
          name: "google_ads_add_negative_keywords",
          status: "completed",
          result: {
            results: [
              entry({
                counts: { added: 401, skipped_existing: 73, failed: 26 },
                samples: {
                  added: [
                    {
                      text: "free",
                      match_type: "EXACT",
                      resource_name: "customers/1234567890/sharedCriteria/50~1",
                    },
                  ],
                  skipped_existing: [{ text: "jobs", match_type: "PHRASE" }],
                  failed: [
                    {
                      scope: "account",
                      message: "The account rejected part of the request.",
                      error_code: "INVALID_INPUT",
                    },
                  ],
                },
                samples_truncated: true,
                audit_note: "Full applied-change details are retained in the audit trail.",
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain("free")
    expect(html).toContain("Account-level error")
    expect(html).toContain("The account rejected part of the request.")
    expect(html).toContain("401")
  })

  it("derives the custom approval summary across incomplete keyword row states", () => {
    const controls = approvalControls()
    const activity: ToolActivity = {
      id: "negative-keywords-incomplete-edits",
      kind: "approval",
      name: "google_ads_add_negative_keywords",
      status: "awaiting_approval",
      args: {
        negative_list: sharedSetReference("50", "Brand Protection"),
        keywords: [{ text: "jobs", match_type: "EXACT" }],
      },
    }
    const columns = [
      { key: "text", label: "Keyword", options: [], placeholder: "", required: true },
      {
        key: "match_type",
        label: "Match Type",
        options: ["EXACT", "PHRASE", "BROAD"],
        placeholder: "",
        required: true,
      },
    ]
    let rows: EditedRecords = [{ text: "jobs", match_type: "EXACT" }]

    assertCustomApproval(activity, controls, rows, "1 keyword", "Exact 1")

    rows = addRecordRow(rows, columns)
    assertCustomApproval(activity, controls, rows, "2 keywords", "Exact 1")

    rows = updateRecordCell(rows, 0, "text", "")
    assertCustomApproval(activity, controls, rows, "2 keywords", "Exact 1")

    rows = updateRecordCell(rows, 0, "text", "new jobs")
    rows = updateRecordCell(rows, 1, "match_type", "PHRASE")
    assertCustomApproval(activity, controls, rows, "2 keywords", "Phrase 1")

    rows = removeRecordRow(removeRecordRow(rows, 1), 0)
    assertCustomApproval(activity, controls, rows, "0 keywords", "Exact 0")

    rows = addRecordRow(rows, columns)
    rows = updateRecordCell(rows, 0, "text", "careers")
    rows = updateRecordCell(rows, 0, "match_type", "BROAD")
    assertCustomApproval(activity, controls, rows, "1 keyword", "Broad 1")
  })

  it("renders the campaign negative keyword approval fan-out summary", () => {
    const controls = approvalControls()
    const html = render(
      googleAdsCampaignNegativeKeywordsPresenter.render(
        props(
          {
            id: "campaign-negative-keywords-approval",
            kind: "approval",
            name: "google_ads_add_campaign_negative_keywords",
            status: "awaiting_approval",
            args: {
              campaign_ids: [
                campaignReference("10", "Brand"),
                campaignReference("20", "Prospecting"),
              ],
              keywords: [
                { text: "free", match_type: "EXACT" },
                { text: "jobs", match_type: "PHRASE" },
                { text: "cheap", match_type: "BROAD" },
              ],
            },
          },
          controls,
          toolUi([])
        )
      )
    )

    expect(html).toContain("3 keywords")
    expect(html).toContain("× 2 campaigns")
    expect(html).toContain("6 proposed changes")
  })

  it("isolates a malformed account outcome without hiding valid siblings", () => {
    const html = render(
      googleAdsCampaignStatusPresenter.render(
        props({
          id: "campaign-mixed-contract",
          kind: "result",
          name: "google_ads_update_campaign_status",
          status: "completed",
          args: { campaign_ids: [campaignReference("10", "Summer Sale")], status: "PAUSED" },
          result: {
            results: [
              entry({
                requested_status: "PAUSED",
                campaigns: [
                  {
                    campaign_id: "10",
                    campaign_name: "Summer Sale",
                    requested_status: "PAUSED",
                    outcome: "updated",
                    external_ref: "customers/1234567890/campaigns/10",
                  },
                ],
              }),
              {
                ...entry({ requested_status: "PAUSED", campaigns: "malformed" }),
                provider_key: "google_ads",
                display_name: "Second account",
                external_id: "2222222222",
              },
            ],
          },
        })
      )
    )

    expect(html).toContain("Updated")
    expect(html).toContain("Second account")
    expect(html).toContain("The system couldn&#x27;t confirm the campaign status outcome.")
  })

  it("distinguishes an unverified mutation from a known failure", () => {
    const html = render(
      googleAdsCampaignStatusPresenter.render(
        props({
          id: "campaign-unverified",
          kind: "result",
          name: "google_ads_update_campaign_status",
          status: "completed",
          args: { campaign_ids: [campaignReference("10", "Summer Sale")], status: "PAUSED" },
          result: {
            results: [
              {
                ...entry({
                  campaigns: [
                    {
                      campaign_id: "10",
                      campaign_name: "Evidence-only campaign",
                      requested_status: "PAUSED",
                      outcome: "updated",
                      external_ref: "customers/1234567890/campaigns/10",
                    },
                  ],
                }),
                status: "error",
                error_code: "unverified_mutation",
                error_message: "request outcome unknown",
              },
            ],
          },
        })
      )
    )

    expect(html).toContain("The system couldn&#x27;t verify whether Google Ads updated")
    expect(html).not.toContain("request outcome unknown")
    expect(html).not.toContain("Evidence-only campaign")
  })

  it("keeps every label row visible when one label is unverified", () => {
    const html = render(
      googleAdsCreateLabelsPresenter.render(
        props({
          id: "labels-unverified",
          kind: "result",
          name: "google_ads_create_labels",
          status: "completed",
          args: {},
          result: {
            results: [
              {
                ...entry({
                  labels: [
                    {
                      name: "Q4",
                      outcome: "created",
                      reference: {
                        entity_kind: "google_ads_label",
                        customer_id: "111",
                        label_id: "8",
                      },
                    },
                    { name: "Q1", outcome: "unverified", error_code: "UNACCOUNTED_OPERATION" },
                  ],
                }),
                status: "error",
                error_code: "unverified_mutation",
              },
            ],
          },
        })
      )
    )

    expect(html).toContain("Q4")
    expect(html).toContain("Q1")
  })

  it("rejects the superseded campaign-link result shape without reconstructing saved arguments", () => {
    const html = render(
      googleAdsCampaignLinksPresenter.render(
        props({
          id: "campaign-link-old-shape",
          kind: "result",
          name: "google_ads_link_negative_keyword_list",
          status: "completed",
          args: {
            action: "LINK",
            campaign_ids: [campaignReference("10", "Summer Sale")],
            negative_list: sharedSetReference("50", "Brand Protection"),
          },
          result: {
            results: [
              entry({
                resource_names: ["customers/1234567890/campaignSharedSets/10~50"],
                skipped_existing: [],
                campaign_errors: [],
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain("The system couldn&#x27;t confirm the campaign shared list outcome.")
    expect(html).not.toContain("List ID 50")
  })

  it("falls through for malformed read payloads", () => {
    expect(
      googleAdsReportPresenter.render(
        props({
          id: "report-1",
          kind: "result",
          name: "google_ads_run_report",
          status: "completed",
          result: { results: [entry({ rows: "bad" })] },
        })
      )
    ).toBeNull()
  })

  it("loads and renders the report presenter through the production registry seam", async () => {
    await loadIntegrationUiModules(["google_ads"])

    const row = renderCustomToolCallRow(
      props({
        id: "report-registry-1",
        kind: "result",
        name: "google_ads_run_report",
        status: "completed",
        result: {
          results: [
            entry({
              rows: [],
              row_count: 0,
              truncated: false,
              truncation_note: null,
            }),
          ],
        },
      })
    )
    const html = render(row)

    expect(html).toContain('aria-label="Google Ads report results"')
  })
})

function props(
  activity: ToolActivity,
  approvalDecision?: Parameters<
    typeof googleAdsCampaignStatusPresenter.render
  >[0]["approvalDecision"],
  ui?: ToolUi
) {
  return {
    activity,
    ...(approvalDecision ? { approvalDecision } : {}),
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "google_ads",
    ...(ui ? { ui } : {}),
  }
}

function field(
  key: string,
  label: string,
  format: ToolUiField["format"],
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
    icon: "google_ads",
    result_fields: [],
    running_label: "",
  }
}

function deviceBidModifierFields(): ToolUiField[] {
  return [
    field("campaign_ids", "Campaigns", "entity_list", true),
    {
      ...field("adjustments", "Device Bid Adjustments", "records", true),
      min_rows: 1,
      columns: [
        {
          key: "device",
          label: "Device",
          options: ["DESKTOP", "MOBILE", "TABLET"],
          placeholder: "",
          required: true,
        },
        {
          key: "bid_modifier",
          label: "Bid Modifier",
          options: [],
          placeholder: "",
          required: true,
        },
      ],
    },
  ]
}

function campaignReference(externalId: string, label: string) {
  return {
    version: 1,
    entity_kind: "google_ads_campaign",
    customer_id: "1234567890",
    campaign_id: externalId,
    label,
  }
}

function sharedSetReference(externalId: string, label: string) {
  return {
    version: 1,
    entity_kind: "google_ads_shared_set",
    customer_id: "1234567890",
    shared_set_id: externalId,
    label,
  }
}

function entry(data: unknown) {
  return {
    provider_key: "google_ads",
    display_name: "Client account",
    external_id: "1234567890",
    status: "success",
    data,
    error_message: null,
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

function assertCustomApproval(
  activity: ToolActivity,
  controls: ReturnType<typeof approvalControls>,
  rows: EditedRecords,
  expectedTotal: string,
  expectedCount: string
) {
  controls.decision.edits = { keywords: rows }
  const rendered = googleAdsListNegativeKeywordsPresenter.render(
    props(activity, controls, toolUi([]))
  )

  expect(isValidElement(rendered)).toBe(true)
  if (isValidElement<{ controls: unknown }>(rendered)) {
    expect(rendered.type).toBe(ToolApprovalDecisionCard)
    expect(rendered.props.controls).toBe(controls)
  }
  const html = render(rendered)
  expect(html).toContain(expectedTotal)
  expect(html).toContain(expectedCount)
  expect(html).toContain("Approve &amp; Add")
  expect(html).toContain("Decline")
}

function render(node: ReactNode) {
  return renderToStaticMarkup(createElement("div", null, node))
}
