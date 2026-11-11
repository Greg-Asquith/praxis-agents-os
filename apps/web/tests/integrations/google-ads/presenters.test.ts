// apps/web/tests/integrations/google-ads/presenters.test.ts

import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import type { ToolUi, ToolUiField } from "@/features/tools/types"
import type { ToolActivity } from "@/integrations/contract"
import { googleAdsAccountsPresenter } from "@/integrations/google_ads/presenters/accounts"
import { googleAdsCreateLabelsPresenter } from "@/integrations/google_ads/presenters/create-labels"
import { googleAdsLabelAssociationsPresenter } from "@/integrations/google_ads/presenters/label-associations"
import { googleAdsReportPresenter } from "@/integrations/google_ads/presenters/report"
import { loadIntegrationUiModules } from "@/integrations/registry"

describe("Google Ads tool presenters", () => {
  it("renders one accounts table with each account's own currency and limit left", () => {
    const account = {
      auto_tagging_enabled: true,
      billing: {
        active_limit: {
          account_budget: { account_budget_id: "12" },
          ends: null,
          left: "658.25",
          limit: "3000",
          served: "2341.75",
        },
        billing_setup: { billing_setup_id: "71" },
        pending_changes: [],
        queued_limits: [],
        state: "running_low",
      },
      cost_this_month: "24906.55",
      cost_today: "1284.1",
      currency: "GBP",
      customer_id: "4821930571",
      manager: false,
      name: "Northwind Outdoor UK",
      status: "ENABLED",
      time_zone: "Europe/London",
    }
    const html = render(
      googleAdsAccountsPresenter.render(
        props({
          id: "accounts-1",
          kind: "result",
          name: "google_ads_get_accounts",
          status: "completed",
          args: {},
          result: {
            results: [
              entry(account),
              entry({
                ...account,
                billing: null,
                cost_this_month: "8115.2",
                cost_today: "402.88",
                currency: "EUR",
                customer_id: "7315520094",
                name: "Northwind Outdoor IE",
                time_zone: "Europe/Dublin",
              }),
            ],
          },
        })
      )
    )

    expect(html).toMatch(/£1,284\.10/)
    expect(html).toMatch(/€8,115\.20/)
    expect(html).toMatch(/£658\.25/)
    expect(html).toContain("482-193-0571")
  })

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

  it.each([
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
    {
      presenter: googleAdsLabelAssociationsPresenter,
      name: "google_ads_apply_labels",
      key: "associations",
      row: {
        label_id: "8",
        label_name: "Black Friday",
        target_kind: "campaign",
        target_id: "10",
        target_name: "Summer Sale",
        outcome: "applied",
      },
      label: "Summer Sale",
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

  it("groups label approval targets by type without dumping raw arguments", () => {
    const html = render(
      googleAdsLabelAssociationsPresenter.render(
        props(
          {
            id: "remove-labels-approval",
            kind: "approval",
            name: "google_ads_remove_labels",
            status: "awaiting_approval",
            args: {
              labels: [{ entity_kind: "google_ads_label", customer_id: "111", label_id: "8" }],
              targets: [
                { kind: "campaign", campaign: campaignReference("10", "Summer Sale") },
                {
                  kind: "keyword",
                  keyword: { ad_group_id: "20", criterion_id: "30", label: "red shoes" },
                },
              ],
            },
          },
          approvalControls(),
          toolUi([])
        )
      )
    )

    expect(html).toContain("Summer Sale")
    expect(html).toContain("red shoes")
    expect(html).not.toContain("&quot;kind&quot;")
    expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>Approve &amp; Remove<\/button>/)
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
  approvalDecision?: Parameters<typeof googleAdsAccountsPresenter.render>[0]["approvalDecision"],
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

function campaignReference(externalId: string, label: string) {
  return {
    version: 1,
    entity_kind: "google_ads_campaign",
    customer_id: "1234567890",
    campaign_id: externalId,
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

function render(node: ReactNode) {
  return renderToStaticMarkup(createElement("div", null, node))
}
