import { describe, expect, it } from "vitest"

import {
  columnsFromHeaders,
  formatDateRange,
  formatDateToken,
  formatFilterSummary,
  metricLabel,
  parseReportData,
} from "@/integrations/google_analytics/lib/report-model"
import { reportDetails } from "@/integrations/google_analytics/lib/tool-details"

describe("Google Analytics report model", () => {
  it("derives typed columns from report headers", () => {
    expect(
      columnsFromHeaders(
        ["date", "dateHour", "dateRange", "country"],
        [
          { name: "sessions", type: "TYPE_INTEGER" },
          { name: "engagementRate", type: "TYPE_FLOAT" },
          { name: "purchaseRevenue", type: "TYPE_CURRENCY" },
          { name: "averageSessionDuration", type: "TYPE_SECONDS" },
        ],
        "GBP"
      )
    ).toEqual([
      { key: "date", kind: "date", label: "Date" },
      { key: "dateHour", kind: "datetime", label: "Date Hour" },
      { key: "dateRange", kind: "badge", label: "Date Range" },
      { key: "country", kind: "text", label: "Country" },
      { key: "sessions", kind: "number", label: "Sessions", isMetric: true },
      { key: "engagementRate", kind: "percent", label: "Engagement Rate", isMetric: true },
      {
        key: "purchaseRevenue",
        kind: "currency",
        label: "Purchase Revenue",
        isMetric: true,
        currencyCode: "GBP",
      },
      {
        key: "averageSessionDuration",
        kind: "number",
        label: "Average Session Duration",
        isMetric: true,
        unit: "seconds",
      },
    ])
  })

  it("formats common labels, dates, ranges, and leaf filters", () => {
    expect(metricLabel("screenPageViews")).toBe("Views")
    expect(metricLabel("sessionKeyEventRate")).toBe("Session Key Event Rate")
    expect(formatDateToken("20260817")).toBe("2026-08-17")
    expect(formatDateToken("2026081712")).toBe("2026-08-17T12:00:00")
    expect(formatDateToken("yesterday")).toBe("yesterday")
    expect(formatDateRange({ start_date: "28daysAgo", end_date: "yesterday", name: null })).toBe(
      "28 days ago → Yesterday"
    )
    expect(formatDateRange({ start_date: "2026-08-01", end_date: "2026-08-17", name: null })).toBe(
      "2026-08-01 → 2026-08-17"
    )
    expect(
      formatFilterSummary({
        field_name: "country",
        negate: false,
        string_filter: { match_type: "EXACT", value: "United Kingdom" },
      })
    ).toBe("Country is United Kingdom")
    expect(
      formatFilterSummary({
        field_name: "sessions",
        negate: false,
        numeric_filter: { operation: "GREATER_THAN", value: 10 },
      })
    ).toBe("Sessions > 10")
  })

  it("formats date and duration values while rejecting malformed results", () => {
    const result = parseReportData({
      rows: [{ date: "20260817", sessions: 12, averageSessionDuration: 92 }],
      row_count: 1,
      truncated: false,
      truncation_note: null,
      totals: [{ sessions: 12, averageSessionDuration: 92 }],
      maximums: [],
      minimums: [],
      dimension_headers: ["date"],
      metric_headers: [
        { name: "sessions", type: "TYPE_INTEGER" },
        { name: "averageSessionDuration", type: "TYPE_SECONDS" },
      ],
      metadata: {
        currency_code: "GBP",
        sampled: false,
        sampling_notes: [],
        data_loss_from_other_row: false,
        thresholded: false,
      },
    })
    expect(result?.rows).toEqual([{ date: "2026-08-17", sessions: 12, averageSessionDuration: 92 }])
    expect(parseReportData({ rows: "bad" })).toBeNull()
  })

  it("summarizes report filters and ordering in operator language", () => {
    expect(
      reportDetails({
        metrics: ["sessions"],
        dimensions: ["country"],
        date_ranges: [{ start_date: "28daysAgo", end_date: "yesterday" }],
        dimension_filter: [
          {
            field_name: "country",
            string_filter: { match_type: "EXACT", value: "United Kingdom" },
          },
        ],
        metric_filter: [
          {
            field_name: "sessions",
            numeric_filter: { operation: "GREATER_THAN", value: 10 },
          },
        ],
        order_bys: [{ metric: "sessions", desc: true }],
        limit: 100,
      })
    ).toEqual([
      { label: "Metrics", value: "Sessions" },
      { label: "Dimensions", value: "Country" },
      { label: "Range", value: "28 days ago → Yesterday" },
      { label: "Filters", summary: false, value: "Country is United Kingdom; Sessions > 10" },
      { label: "Order", value: "by Sessions, desc" },
      { label: "Limit", value: "100" },
    ])
  })
})
