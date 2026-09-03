// apps/web/tests/integrations/google-search-console/models.test.ts

import { describe, expect, it } from "vitest"

import { parseSearchAnalyticsData } from "@/integrations/google_search_console/lib/search-analytics-model"
import { parseSitemapsData } from "@/integrations/google_search_console/lib/sitemaps-model"
import { searchAnalyticsDetails } from "@/integrations/google_search_console/lib/tool-details"

describe("Google Search Console presenter models", () => {
  it("parses typed search rows and derives dimension and metric columns", () => {
    const parsed = parseSearchAnalyticsData(searchData())

    expect(parsed?.columns).toEqual([
      { key: "query", kind: "text", label: "Query" },
      { key: "page", kind: "link", label: "Page" },
      { key: "date", kind: "date", label: "Date" },
      { key: "clicks", kind: "number", label: "Clicks", isMetric: true },
      { key: "impressions", kind: "number", label: "Impressions", isMetric: true },
      { key: "ctr", kind: "percent", label: "CTR", isMetric: true },
      { key: "position", kind: "number", label: "Position", isMetric: true },
    ])
    expect(parsed?.rows[0]?.["query"]).toEqual(node("organic growth"))
  })

  it("parses sitemap rows into operator-facing status values", () => {
    const parsed = parseSitemapsData(sitemapData())

    expect(parsed?.[0]).toMatchObject({
      errors: 0,
      path: node("https://example.com/sitemap.xml", "search_console_sitemap"),
      pending: "Processed",
      submitted_url_count: 42,
      type: "Sitemap index",
      warnings: 1,
    })
  })

  it("rejects malformed provider data", () => {
    expect(
      parseSearchAnalyticsData({ ...searchData(), rows: [{ keys: {}, clicks: "12" }] })
    ).toBeNull()
    expect(parseSitemapsData({ ...sitemapData(), sitemaps: [{ path: "plain" }] })).toBeNull()
  })

  it("summarizes query arguments in operator language", () => {
    expect(
      searchAnalyticsDetails({
        start_date: "2026-08-01",
        end_date: "2026-08-28",
        dimensions: ["query", "page"],
        search_type: "web",
        filters: [{ dimension: "country", operator: "equals", expression: "gbr" }],
        row_limit: 100,
      })
    ).toEqual([
      { label: "Range", value: "2026-08-01 → 2026-08-28" },
      { label: "Dimensions", value: "Query, Page" },
      { label: "Search type", value: "Web" },
      { label: "Filters", summary: false, value: "Country is gbr" },
      { label: "Row limit", value: "100" },
    ])
  })

  it("shows effective defaults when optional query arguments are omitted", () => {
    expect(
      searchAnalyticsDetails({
        start_date: "2026-08-01",
        end_date: "2026-08-28",
      })
    ).toEqual([
      { label: "Range", value: "2026-08-01 → 2026-08-28" },
      { label: "Search type", value: "Web" },
      { label: "Row limit", value: "100" },
    ])
  })
})

function searchData() {
  return {
    rows: [
      {
        keys: {
          query: node("organic growth"),
          page: node("https://example.com/growth"),
          date: "2026-08-20",
        },
        clicks: 12,
        impressions: 240,
        ctr: 0.05,
        position: 3.2,
      },
    ],
    row_count: 1,
    truncated: false,
    truncation_note: null,
    response_aggregation_type: "byPage",
    start_date: "2026-08-01",
    end_date: "2026-08-28",
    search_type: "web",
  }
}

function sitemapData() {
  return {
    sitemaps: [
      {
        path: node("https://example.com/sitemap.xml", "search_console_sitemap"),
        type: "sitemap",
        last_submitted: "2026-08-20T10:00:00Z",
        last_downloaded: "2026-08-21T10:00:00Z",
        is_pending: false,
        is_sitemaps_index: true,
        warnings: 1,
        errors: 0,
        contents: [{ type: "web", submitted: 42 }],
        submitted_url_count: 42,
      },
    ],
    sitemap_count: 1,
  }
}

function node(content: string, sourceKind = "search_console_row") {
  return {
    node: "praxis_untrusted" as const,
    source_kind: sourceKind,
    source_ref: "https://example.com/",
    content,
  }
}
