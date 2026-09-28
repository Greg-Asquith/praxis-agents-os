import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import { googleAnalyticsCompatibilityPresenter } from "@/integrations/google_analytics/presenters/compatibility"
import { googleAnalyticsGoogleAdsLinksPresenter } from "@/integrations/google_analytics/presenters/google-ads-links"
import { googleAnalyticsRealtimePresenter } from "@/integrations/google_analytics/presenters/realtime"
import { googleAnalyticsReportPresenter } from "@/integrations/google_analytics/presenters/report"
import { googleAnalyticsReportFieldsPresenter } from "@/integrations/google_analytics/presenters/report-fields"

describe("Google Analytics tool presenters", () => {
  it("renders a report table with authoritative totals and honest data-quality notes", () => {
    const html = render(
      googleAnalyticsReportPresenter.render(
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

    expect(html).toContain("12,430")
    expect(html).toContain("18,000")
    expect(html).toContain("2 of 4,213 rows shown")
  })

  it("falls back for malformed results", () => {
    for (const [presenter, name] of [
      [googleAnalyticsReportPresenter, "google_analytics_run_report"],
      [googleAnalyticsRealtimePresenter, "google_analytics_run_realtime_report"],
      [googleAnalyticsReportFieldsPresenter, "google_analytics_list_report_fields"],
      [googleAnalyticsCompatibilityPresenter, "google_analytics_check_report_fields"],
      [googleAnalyticsGoogleAdsLinksPresenter, "google_analytics_list_google_ads_links"],
    ] as const) {
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
