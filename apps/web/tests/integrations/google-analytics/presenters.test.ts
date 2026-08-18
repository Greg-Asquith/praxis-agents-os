import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { compatibilityPresenter } from "@/integrations/google_analytics/presenters/compatibility"
import { googleAdsLinksPresenter } from "@/integrations/google_analytics/presenters/google-ads-links"
import { realtimePresenter } from "@/integrations/google_analytics/presenters/realtime"
import { reportFieldsPresenter } from "@/integrations/google_analytics/presenters/report-fields"
import { reportPresenter } from "@/integrations/google_analytics/presenters/report"
import type { ToolActivity } from "@/integrations/contract"

describe("Google Analytics tool presenters", () => {
  it("renders a report table with authoritative totals and honest data-quality notes", () => {
    const html = render(
      reportPresenter.render(
        props({
          id: "report-1",
          kind: "result",
          name: "google_analytics_run_report",
          status: "completed",
          args: {
            metrics: ["sessions", "keyEvents", "engagementRate"],
            dimensions: ["date", "country"],
            date_ranges: [{ start_date: "28daysAgo", end_date: "yesterday" }],
            metric_filter: [
              {
                field_name: "sessions",
                numeric_filter: { operation: "GREATER_THAN", value: 10 },
              },
            ],
            order_bys: [{ metric: "sessions", desc: true }],
            limit: 2,
          },
          result: {
            results: [
              entry(
                reportData({
                  rows: [
                    {
                      date: "20260817",
                      country: "United Kingdom",
                      sessions: 12430,
                      keyEvents: 318,
                      engagementRate: 0.64,
                    },
                    {
                      date: "20260816",
                      country: "United States",
                      sessions: 1100,
                      keyEvents: 42,
                      engagementRate: 0.5,
                    },
                  ],
                  row_count: 4213,
                  truncated: true,
                  totals: [
                    { sessions: 18000, keyEvents: 500, engagementRate: 0.61 },
                    { sessions: 17000, keyEvents: 450, engagementRate: 0.59 },
                  ],
                  maximums: [{ sessions: 12430, keyEvents: 318, engagementRate: 0.64 }],
                  minimums: [{ sessions: 1100, keyEvents: 42, engagementRate: 0.5 }],
                  metadata: {
                    currency_code: "GBP",
                    sampled: true,
                    sampling_notes: ["12,000 of 40,000 events read for sampled range 'current'"],
                    data_loss_from_other_row: true,
                    thresholded: true,
                  },
                })
              ),
            ],
          },
        })
      )
    )

    expect(html).toContain("Run Google Analytics Report")
    expect(html).toContain("12,430")
    expect(html).toContain("318")
    expect(html).toContain("Totals")
    expect(html).toContain("18,000")
    expect(html).toContain("17,000")
    expect(html).toContain("Minimum")
    expect(html).toContain("Maximum")
    expect(html).toContain("2 of 4,213 rows shown")
    expect(html).toContain("Sampled:")
    expect(html).toContain("privacy thresholds")
    expect(html).toContain("grouped as “(other)”")
    expect(html).toContain("28 days ago → Yesterday")
    expect(html).toContain("by Sessions, desc")
  })

  it("keeps partial failures visible and handles empty report rows", () => {
    const partial = render(
      reportPresenter.render(
        props({
          id: "report-partial",
          kind: "result",
          name: "google_analytics_run_report",
          status: "completed",
          result: {
            results: [
              entry(reportData({ rows: [], row_count: 0 }), { display_name: "Shop" }),
              entry(null, {
                display_name: "App",
                external_id: "456",
                status: "error",
                error_message: "Property access was removed.",
              }),
            ],
          },
        })
      )
    )
    expect(partial).toContain("Tool succeeded")
    expect(partial).toContain("1/2 connections")
    expect(partial).toContain("No report rows returned")
    expect(partial).toContain("Property access was removed")
  })

  it("renders realtime rows and windows without date formatting", () => {
    const html = render(
      realtimePresenter.render(
        props({
          id: "realtime-1",
          kind: "result",
          name: "google_analytics_run_realtime_report",
          status: "completed",
          args: {
            metrics: ["activeUsers"],
            dimensions: ["country"],
            minute_ranges: [{ start_minutes_ago: 29, end_minutes_ago: 0 }],
          },
          result: {
            results: [
              entry({
                rows: [{ country: "United Kingdom", activeUsers: 27 }],
                row_count: 1,
                truncated: false,
                truncation_note: null,
                totals: [{ activeUsers: 27 }],
                maximums: [],
                minimums: [],
                metric_headers: [{ name: "activeUsers", type: "TYPE_INTEGER" }],
                dimension_headers: ["country"],
                window: [{ start_minutes_ago: 29, end_minutes_ago: 0 }],
              }),
            ],
          },
        })
      )
    )
    expect(html).toContain("Right now (last 30 minutes)")
    expect(html).toContain("United Kingdom")
    expect(html).toContain("27")
    expect(html).toContain("29 → 0 minutes ago")
  })

  it("renders dimension and metric field tables with counts", () => {
    const html = render(
      reportFieldsPresenter.render(
        props({
          id: "fields-1",
          kind: "result",
          name: "google_analytics_list_report_fields",
          status: "completed",
          args: { kind: "both", limit: 1 },
          result: {
            results: [
              entry({
                dimensions: [field("country", "Country", false)],
                metrics: [
                  {
                    ...field("customEvent:lead_score", "Lead score", true),
                    type: "TYPE_FLOAT",
                    blocked_reasons: [],
                  },
                ],
                dimension_count: 4,
                metric_count: 3,
                truncated: true,
              }),
            ],
          },
        })
      )
    )
    expect(html).toContain("Dimensions")
    expect(html).toContain("Metrics")
    expect(html).toContain("API name")
    expect(html).toContain("customEvent:lead_score")
    expect(html).toContain("Custom")
    expect(html).toContain("1 of 4 fields shown")
    expect(html).toContain("1 of 3 fields shown")
  })

  it("renders compatible and incompatible field status lists", () => {
    const compatible = render(
      compatibilityPresenter.render(props(compatibilityActivity(true, [], "compatible")))
    )
    const incompatible = render(
      compatibilityPresenter.render(
        props(compatibilityActivity(false, ["itemName", "eventCount"], "incompatible"))
      )
    )
    expect(compatible).toContain("These can be reported together")
    expect(compatible).toContain("Compatible")
    expect(incompatible).toContain("2 fields can&#x27;t be combined")
    expect(incompatible).toContain("Incompatible")
    expect(incompatible).toContain("itemName")
  })

  it("renders linked Google Ads accounts with operator-friendly ids and status", () => {
    const html = render(
      googleAdsLinksPresenter.render(
        props({
          id: "links-1",
          kind: "result",
          name: "google_analytics_list_google_ads_links",
          status: "completed",
          result: {
            results: [
              entry({
                links: [
                  {
                    customer_id: "1234567890",
                    can_manage_clients: true,
                    ads_personalization_enabled: false,
                    created_at: "2026-08-17T09:30:00Z",
                  },
                ],
                link_count: 1,
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain("List Linked Google Ads Accounts")
    expect(html).toContain("123-456-7890")
    expect(html).toContain("Manager")
    expect(html).toContain("Disabled")
    expect(html).toContain("1 linked account")
  })

  it("renders an honest empty linked-account state", () => {
    const html = render(
      googleAdsLinksPresenter.render(
        props({
          id: "links-empty",
          kind: "result",
          name: "google_analytics_list_google_ads_links",
          status: "completed",
          result: { results: [entry({ links: [], link_count: 0 })] },
        })
      )
    )

    expect(html).toContain("No Google Ads accounts are linked to this property")
  })

  it("renders every loading state and falls back for malformed results", () => {
    for (const [presenter, name, label] of [
      [reportPresenter, "google_analytics_run_report", "Running Google Analytics report"],
      [realtimePresenter, "google_analytics_run_realtime_report", "realtime report"],
      [
        reportFieldsPresenter,
        "google_analytics_list_report_fields",
        "Listing Google Analytics report fields",
      ],
      [
        compatibilityPresenter,
        "google_analytics_check_report_fields",
        "Checking Google Analytics report fields",
      ],
      [
        googleAdsLinksPresenter,
        "google_analytics_list_google_ads_links",
        "Listing linked Google Ads accounts",
      ],
    ] as const) {
      expect(
        render(presenter.render(props({ id: name, kind: "call", name, status: "running" })))
      ).toContain(label)
      expect(
        presenter.render(
          props({
            id: `${name}-bad`,
            kind: "result",
            name,
            status: "completed",
            result: { results: [entry({ bad: true })] },
          })
        )
      ).toBeNull()
    }
  })
})

function compatibilityActivity(
  compatible: boolean,
  incompatibleFields: string[],
  id: string
): ToolActivity {
  return {
    id,
    kind: "result",
    name: "google_analytics_check_report_fields",
    status: "completed",
    result: {
      results: [
        entry({
          compatible,
          dimensions: [
            { api_name: "itemName", compatibility: compatible ? "COMPATIBLE" : "INCOMPATIBLE" },
          ],
          metrics: [
            { api_name: "eventCount", compatibility: compatible ? "COMPATIBLE" : "INCOMPATIBLE" },
          ],
          incompatible_fields: incompatibleFields,
        }),
      ],
    },
  }
}

function reportData(overrides: Record<string, unknown> = {}) {
  return {
    rows: [
      {
        date: "20260817",
        country: "United Kingdom",
        sessions: 12,
        keyEvents: 3,
        engagementRate: 0.5,
      },
    ],
    row_count: 1,
    truncated: false,
    truncation_note: null,
    totals: [],
    maximums: [],
    minimums: [],
    metric_headers: [
      { name: "sessions", type: "TYPE_INTEGER" },
      { name: "keyEvents", type: "TYPE_INTEGER" },
      { name: "engagementRate", type: "TYPE_FLOAT" },
    ],
    dimension_headers: ["date", "country"],
    metadata: {
      currency_code: "GBP",
      sampled: false,
      sampling_notes: [],
      data_loss_from_other_row: false,
      thresholded: false,
    },
    ...overrides,
  }
}

function field(apiName: string, uiName: string, custom: boolean) {
  return {
    api_name: apiName,
    ui_name: uiName,
    description: "Field description",
    category: "User",
    custom,
  }
}

function entry(data: unknown, overrides: Record<string, unknown> = {}) {
  return {
    provider_key: "google_analytics",
    display_name: "Website",
    external_id: "123",
    status: "success",
    data,
    error_code: null,
    error_message: null,
    ...overrides,
  }
}

function props(activity: ToolActivity) {
  return {
    activity,
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "google_analytics",
  }
}

function render(node: ReactNode) {
  return renderToStaticMarkup(createElement("div", null, node))
}
