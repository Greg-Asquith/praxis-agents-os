// apps/web/tests/integrations/google-search-console/presenters.test.ts

import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeAll, describe, expect, it } from "vitest"

import { ToolCallRow } from "@/features/conversations/components/tool-call-row"
import { toolPresentationsQueryOptions } from "@/features/tools/api/list-tool-presentations"
import type { ToolActivity } from "@/integrations/contract"
import { googleSearchConsoleInspectionPresenter } from "@/integrations/google_search_console/presenters/inspection"
import { googleSearchConsoleSearchAnalyticsPresenter } from "@/integrations/google_search_console/presenters/search-analytics"
import { googleSearchConsoleSitemapsPresenter } from "@/integrations/google_search_console/presenters/sitemaps"
import { loadIntegrationUiModules } from "@/integrations/registry"

describe("Google Search Console presenters", () => {
  beforeAll(async () => {
    await loadIntegrationUiModules(["google_search_console"])
  })

  it("renders a bounded Search Analytics table and query details", () => {
    const html = render(
      googleSearchConsoleSearchAnalyticsPresenter.render(
        props({
          id: "search-1",
          kind: "result",
          name: "google_search_console_query_search_analytics",
          status: "completed",
          args: {
            start_date: "2026-08-01",
            end_date: "2026-08-28",
            dimensions: ["query", "page"],
            search_type: "web",
            row_limit: 10,
          },
          result: { results: [entry(searchData())] },
        })
      )
    )

    expect(html).toContain("Query Search Analytics")
    expect(html).toContain("organic growth")
    expect(html).toContain("https://example.com/growth")
    expect(html).toContain("12")
    expect(html).toContain("5%")
    expect(html).toContain("3.2")
    expect(html).toContain("2026-08-01 → 2026-08-28")
    expect(html).toContain("The result may contain more rows")
  })

  it("renders sitemap status and an honest empty state", () => {
    const populated = render(
      googleSearchConsoleSitemapsPresenter.render(
        props({
          id: "sitemaps-1",
          kind: "result",
          name: "google_search_console_list_sitemaps",
          status: "completed",
          result: { results: [entry(sitemapData())] },
        })
      )
    )
    const empty = render(
      googleSearchConsoleSitemapsPresenter.render(
        props({
          id: "sitemaps-empty",
          kind: "result",
          name: "google_search_console_list_sitemaps",
          status: "completed",
          result: { results: [entry({ sitemaps: [], sitemap_count: 0 })] },
        })
      )
    )

    expect(populated).toContain("List Search Console Sitemaps")
    expect(populated).toContain("sitemap.xml")
    expect(populated).toContain("Sitemap Index")
    expect(populated).toContain("Processed")
    expect(populated).toContain("42")
    expect(empty).toContain("No submitted sitemaps were found")
  })

  it("renders loading and partial-failure states and rejects malformed results", () => {
    expect(
      render(
        googleSearchConsoleSearchAnalyticsPresenter.render(
          props({
            id: "search-running",
            kind: "call",
            name: "google_search_console_query_search_analytics",
            status: "running",
          })
        )
      )
    ).toContain("Querying Search Analytics")
    expect(
      render(
        googleSearchConsoleSitemapsPresenter.render(
          props({
            id: "sitemaps-running",
            kind: "call",
            name: "google_search_console_list_sitemaps",
            status: "running",
          })
        )
      )
    ).toContain("Listing Search Console sitemaps")

    const partial = render(
      googleSearchConsoleSearchAnalyticsPresenter.render(
        props({
          id: "search-partial",
          kind: "result",
          name: "google_search_console_query_search_analytics",
          status: "completed",
          result: {
            results: [
              entry({ ...searchData(), rows: [], row_count: 0 }),
              entry(null, {
                display_name: "Store",
                external_id: "https://store.example.com/",
                status: "error",
                error_message: "Search Console access was removed.",
              }),
            ],
          },
        })
      )
    )
    expect(partial).toContain("1/2 connections")
    expect(partial).toContain("No search performance rows returned")
    expect(partial).toContain("Search Console access was removed")

    expect(
      googleSearchConsoleSearchAnalyticsPresenter.render(
        props({
          id: "search-bad",
          kind: "result",
          name: "google_search_console_query_search_analytics",
          status: "completed",
          result: { results: [entry({ rows: "bad" })] },
        })
      )
    ).toBeNull()
  })

  it("renders URL inspection details, disclosures, links, loading, and URL errors", () => {
    const populated = render(
      googleSearchConsoleInspectionPresenter.render(
        props({
          id: "inspection-1",
          kind: "result",
          name: "google_search_console_inspect_url",
          status: "completed",
          result: { results: [entry({ inspections: [inspectionData()] })] },
        })
      )
    )
    const failedUrl = render(
      googleSearchConsoleInspectionPresenter.render(
        props({
          id: "inspection-error",
          kind: "result",
          name: "google_search_console_inspect_url",
          status: "completed",
          result: { results: [entry({ inspections: [inspectionError()] })] },
        })
      )
    )
    const empty = render(
      googleSearchConsoleInspectionPresenter.render(
        props({
          id: "inspection-empty",
          kind: "result",
          name: "google_search_console_inspect_url",
          status: "completed",
          result: { results: [entry({ inspections: [] })] },
        })
      )
    )
    const loading = render(
      googleSearchConsoleInspectionPresenter.render(
        props({
          id: "inspection-running",
          kind: "call",
          name: "google_search_console_inspect_url",
          status: "running",
        })
      )
    )

    expect(populated).toContain("Inspect Search Console URLs")
    expect(populated).toContain("Submitted and indexed")
    expect(populated).toContain("Google canonical")
    expect(populated).toContain("Sitemaps")
    expect(populated).toContain("Referring URLs")
    expect(populated).toContain("Product snippets: 2 issues")
    expect(populated).toContain("Open in Search Console")
    expect(failedUrl).toContain("Google could not inspect this URL")
    expect(empty).toContain("No URL inspections were returned")
    expect(loading).toContain("Inspecting Search Console URLs")
    expect(
      googleSearchConsoleInspectionPresenter.render(
        props({
          id: "inspection-bad",
          kind: "result",
          name: "google_search_console_inspect_url",
          status: "completed",
          result: { results: [entry({ inspections: [{ url: 123 }] })] },
        })
      )
    ).toBeNull()
  })

  it("falls through to the declarative row when a presenter rejects malformed data", () => {
    const html = renderToolRow({
      id: "search-default",
      kind: "result",
      name: "google_search_console_query_search_analytics",
      status: "completed",
      result: { results: [entry({ rows: "bad" })] },
    })

    expect(html).toContain("Ran google_search_console_query_search_analytics")
    expect(html).not.toContain('aria-label="Search Analytics results"')
  })

  it("falls through to the declarative row for a malformed crawl timestamp", () => {
    const html = renderToolRow({
      id: "inspection-invalid-date",
      kind: "result",
      name: "google_search_console_inspect_url",
      status: "completed",
      result: {
        results: [
          entry({
            inspections: [{ ...inspectionData(), last_crawl_time: "not-a-timestamp" }],
          }),
        ],
      },
    })

    expect(html).toContain("Ran google_search_console_inspect_url")
    expect(html).not.toContain('aria-label="Search Console URL inspection results"')
  })
})

function searchData() {
  return {
    rows: [
      {
        keys: {
          query: node("organic growth"),
          page: node("https://example.com/growth"),
        },
        clicks: 12,
        impressions: 240,
        ctr: 0.05,
        position: 3.2,
      },
    ],
    row_count: 1,
    truncated: true,
    truncation_note: "The result may contain more rows. Page with start_row or add filters.",
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

function inspectionData() {
  return {
    url: "https://example.com/page",
    verdict: "PASS",
    coverage_state: "Submitted and indexed",
    robots_txt_state: "ALLOWED",
    indexing_state: "INDEXING_ALLOWED",
    page_fetch_state: "SUCCESSFUL",
    crawled_as: "MOBILE",
    last_crawl_time: "2026-08-30T12:30:00Z",
    google_canonical: node("https://example.com/page", "search_console_inspection"),
    user_canonical: node("https://example.com/page", "search_console_inspection"),
    sitemap: [node("https://example.com/sitemap.xml", "search_console_inspection")],
    referring_urls: [node("https://example.com/referrer", "search_console_inspection")],
    mobile_usability_verdict: "PASS",
    rich_results_verdict: "FAIL",
    rich_results: [{ type: "Product snippets", issue_count: 2 }],
    inspection_result_link: "https://search.google.com/search-console/inspect?x=1",
    error_code: null,
    message: null,
  }
}

function inspectionError() {
  return {
    ...inspectionData(),
    verdict: "",
    error_code: "IntegrationNotFoundError",
    message: node("Google could not inspect this URL", "search_console_inspection_error"),
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

function entry(data: unknown, overrides: Record<string, unknown> = {}) {
  return {
    provider_key: "google_search_console",
    display_name: "Example",
    external_id: "https://example.com/",
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
    providerKey: "google_search_console",
  }
}

function render(nodeValue: ReactNode) {
  return renderToStaticMarkup(createElement("div", null, nodeValue))
}

function renderToolRow(activity: ToolActivity) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(toolPresentationsQueryOptions().queryKey, { tools: [] })
  return renderToStaticMarkup(
    createElement(QueryClientProvider, {
      client: queryClient,
      children: createElement(ToolCallRow, { activity, defaultOpen: true }),
    })
  )
}
