// apps/web/tests/integrations/google-search-console/presenters.test.ts

import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeAll, describe, expect, it } from "vitest"

import { ToolCallRow } from "@/features/conversations/components/tool-call-row"
import { toolPresentationsQueryOptions } from "@/features/tools/api/list-tool-presentations"
import type { ToolActivity } from "@/integrations/contract"
import { googleSearchConsoleSearchAnalyticsPresenter } from "@/integrations/google_search_console/presenters/search-analytics"
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

    expect(html).toContain("organic growth")
    expect(html).toContain("5%")
    expect(html).toContain("The result may contain more rows")
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
