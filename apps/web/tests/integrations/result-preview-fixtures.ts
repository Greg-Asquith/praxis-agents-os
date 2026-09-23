import { googleAdsReportPresenter } from "@/integrations/google_ads/presenters/report"
import { googleAnalyticsReportPresenter } from "@/integrations/google_analytics/presenters/report"
import { googleAnalyticsRealtimePresenter } from "@/integrations/google_analytics/presenters/realtime"
import { googleSearchConsoleSearchAnalyticsPresenter } from "@/integrations/google_search_console/presenters/search-analytics"

export const fileId = "11111111-1111-4111-8111-111111111111"
const rows = Array.from({ length: 50 }, (_, index) => ({
  country: `Country ${String(index)}`,
  sessions: index,
}))
const analytics = {
  rows,
  row_count: 2000,
  truncated: true,
  truncation_note: "Provider returned 1,000 rows.",
  dimension_headers: ["country"],
  metric_headers: [{ name: "sessions", type: "TYPE_INTEGER" }],
  totals: [{ sessions: 999999 }],
  minimums: [],
  maximums: [],
  metadata: {
    currency_code: "GBP",
    sampled: true,
    sampling_notes: [],
    data_loss_from_other_row: false,
    thresholded: true,
  },
}
export const cases = [
  {
    presenter: googleAdsReportPresenter,
    provider: "google_ads",
    data: {
      rows: rows.map((row) => ({
        campaign: { name: row.country },
        metrics: { clicks: row.sessions },
      })),
      row_count: 1000,
      truncated: true,
      truncation_note: "Provider returned 1,000 rows.",
    },
  },
  { presenter: googleAnalyticsReportPresenter, provider: "google_analytics", data: analytics },
  {
    presenter: googleAnalyticsRealtimePresenter,
    provider: "google_analytics",
    data: { ...analytics, window: [] },
  },
  {
    presenter: googleSearchConsoleSearchAnalyticsPresenter,
    provider: "google_search_console",
    data: {
      rows: rows.map((row) => ({
        keys: { query: row.country },
        clicks: row.sessions,
        impressions: 100,
        ctr: 0.1,
        position: 2,
      })),
      row_count: 1000,
      truncated: true,
      truncation_note: "Provider returned 1,000 rows.",
    },
  },
]

export function entry(provider: string, data: unknown) {
  return {
    provider_key: provider,
    external_id: "123",
    display_name: "Website",
    status: "success",
    data,
    error_code: null,
    error_message: null,
  }
}

export function envelope(provider: string, data: unknown) {
  return {
    preview: true,
    file_id: fileId,
    file_name: "report.json",
    file_reference: { version: 1, entity_kind: "file", entity_id: fileId, label: "report.json" },
    data: {
      results: [
        entry(provider, data),
        {
          ...entry(provider, null),
          external_id: "456",
          display_name: "Other account",
          status: "error",
          error_message: "Access was removed.",
        },
      ],
    },
    lists: { "results.0.data.rows": { shown: 50, total: 1000 } } as Record<
      string,
      { shown: number; total: number }
    >,
    hint: "Use the complete retained result.",
  }
}
