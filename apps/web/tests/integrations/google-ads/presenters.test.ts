import { createElement, isValidElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { ToolApprovalDecisionCard } from "@/components/tool-ui/approval-card"
import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import type { ToolActivity } from "@/integrations/contract"
import googleAdsModule from "@/integrations/google_ads"
import { googleAdsAccountsPresenter } from "@/integrations/google_ads/presenters/accounts"
import { googleAdsCampaignStatusPresenter } from "@/integrations/google_ads/presenters/campaign-status"
import { googleAdsReportPresenter } from "@/integrations/google_ads/presenters/report"
import { integrationToolRowPresenters, loadIntegrationUiModules } from "@/integrations/registry"

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

    expect(html).toContain("Run Google Ads Report")
    expect(html).toContain("Customer ID")
    expect(html).toContain("123-456-7890")
    expect(html).toMatch(/£1\.25|GBP\s*1\.25/)
    expect(html).toContain("12.5%")
    expect(html).toContain("25%")
    expect(html).toContain("£73.04")
    expect(html).toContain("£51.05")
    expect(html).toContain(">Average CPC<")
    expect(html).toContain(">Cost Per Conversion<")
    expect(html).toContain("987654")
    expect(html).toContain(">Cost<")
    expect(html).toContain(">Resource Name<")
    expect(html).toContain(">CTR<")
    expect(html).toContain(">ID<")
    expect(html).not.toContain(">Metrics Cost Micros<")
    expect(html).not.toContain(">Campaign Resource Name<")
    expect(html).toContain("Report limited to 1 row.")
    expect(html).toContain("Download Report CSV")
    expect(html).toContain("Open row 1 details")
    expect(html).toContain("Total")
    expect(html).not.toContain("praxis_untrusted")
    expect(html).not.toContain("PRAXIS_UNTRUSTED_CONTENT")
  })

  it("renders report and account loading states", () => {
    expect(
      render(
        googleAdsReportPresenter.render(
          props({
            id: "report-1",
            kind: "call",
            name: "google_ads_run_report",
            status: "running",
          })
        )
      )
    ).toContain("Running Google Ads report…")
    expect(
      render(
        googleAdsAccountsPresenter.render(
          props({
            id: "accounts-1",
            kind: "call",
            name: "google_ads_list_accounts",
            status: "running",
          })
        )
      )
    ).toContain("Loading Google Ads accounts…")
  })

  it("renders the account hierarchy with business ids and capability badges", () => {
    const html = render(
      googleAdsAccountsPresenter.render(
        props({
          id: "accounts-1",
          kind: "result",
          name: "google_ads_list_accounts",
          status: "completed",
          result: {
            results: [
              entry({
                accounts: [
                  {
                    customer_id: "1111111111",
                    display_name: "Agency manager",
                    parent_customer_id: null,
                    manager: true,
                    currency_code: "GBP",
                    status: "ENABLED",
                    writable: false,
                    enabled: true,
                  },
                  {
                    customer_id: "2222222222",
                    display_name: "Client account",
                    parent_customer_id: "1111111111",
                    manager: false,
                    currency_code: "GBP",
                    status: "PAUSED",
                    writable: true,
                    enabled: false,
                  },
                ],
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain("Agency manager")
    expect(html).toContain("Client account")
    expect(html).toContain("111-111-1111")
    expect(html).toContain("222-222-2222")
    expect(html).toContain("Manager")
    expect(html).toContain("Writable")
    expect(html).toContain("Read only")
    expect(html).toContain("Not selected")
  })

  it("uses the existing approval controls with an editable status and strong warning", () => {
    const controls = approvalControls()
    const rendered = googleAdsCampaignStatusPresenter.render(
      props(
        {
          id: "campaign-1",
          kind: "approval",
          name: "google_ads_update_campaign_status",
          status: "awaiting_approval",
          args: { campaign_ids: ["10", "20"], status: "PAUSED" },
        },
        controls
      )
    )

    expect(isValidElement(rendered)).toBe(true)
    if (
      isValidElement<{
        controls: unknown
        fields: { key: string; editable: boolean; options: string[] }[]
      }>(rendered)
    ) {
      expect(rendered.type).toBe(ToolApprovalDecisionCard)
      expect(rendered.props.controls).toBe(controls)
      expect(rendered.props.fields).toContainEqual(
        expect.objectContaining({
          key: "status",
          editable: true,
          options: ["ENABLED", "PAUSED"],
        })
      )
    }
    const html = render(rendered)
    expect(html).toContain("This changes live campaign delivery.")
    expect(html).toContain("10")
    expect(html).toContain("20")
    expect(html).toContain("Approve &amp; Update")
  })

  it("renders mixed campaign outcomes with per-campaign status and inline errors", () => {
    const html = render(
      googleAdsCampaignStatusPresenter.render(
        props({
          id: "campaign-1",
          kind: "result",
          name: "google_ads_update_campaign_status",
          status: "completed",
          args: { campaign_ids: ["10", "20"], status: "PAUSED" },
          result: {
            results: [
              entry({
                resource_names: ["customers/1234567890/campaigns/10"],
                campaign_errors: [
                  {
                    campaign_id: "20",
                    message: "Campaign is removed.",
                    error_code: "CANNOT_MODIFY_REMOVED_CAMPAIGN",
                  },
                ],
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain("Succeeded")
    expect(html).toContain("Failed")
    expect(html).toContain("10")
    expect(html).toContain("20")
    expect(html).toContain("Campaign is removed.")
    expect(html).toContain("Updated")
  })

  it.each([
    ["running", "Updating Google Ads campaigns…"],
    ["awaiting_approval", "Waiting for campaign approval…"],
    ["denied", "Nothing was changed."],
    ["failed", "No campaign change was confirmed."],
    ["unknown", "No campaign change was confirmed."],
  ] as const)("renders an honest %s lifecycle state", (status, expected) => {
    const html = render(
      googleAdsCampaignStatusPresenter.render(
        props({
          id: "campaign-1",
          kind: "call",
          name: "google_ads_update_campaign_status",
          status,
          args: { campaign_ids: ["10"], status: "PAUSED" },
        })
      )
    )
    expect(html).toContain(expected)
  })

  it("falls through for malformed read payloads and registers all presenters", () => {
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
    expect(googleAdsModule.toolRowPresenters.map((presenter) => presenter.key)).toEqual([
      "google-ads-run-report",
      "google-ads-list-accounts",
      "google-ads-update-campaign-status",
    ])
    expect(googleAdsCampaignStatusPresenter.handlesApprovals).toBe(true)
  })

  it("loads and renders the report presenter through the production registry seam", async () => {
    await loadIntegrationUiModules(["google_ads"])

    expect(integrationToolRowPresenters("google_ads").map((presenter) => presenter.key)).toContain(
      "google-ads-run-report"
    )
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
    expect(html).toContain("Run Google Ads Report")
    expect(html).not.toContain("GAQL Query")
  })
})

function props(
  activity: ToolActivity,
  approvalDecision?: Parameters<
    typeof googleAdsCampaignStatusPresenter.render
  >[0]["approvalDecision"]
) {
  return {
    activity,
    ...(approvalDecision ? { approvalDecision } : {}),
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "google_ads",
  }
}

function entry(data: unknown) {
  return {
    connection_id: "connection-1",
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
