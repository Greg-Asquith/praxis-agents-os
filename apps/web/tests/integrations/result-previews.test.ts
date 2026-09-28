import { createElement } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { parseResultPreview } from "@/components/tool-ui/result-preview"
import type { ToolRowPresenter } from "@/integrations/contract"
import { bigQueryQueryPresenter } from "@/integrations/bigquery/presenters/query"
import { googleAdsReportPresenter } from "@/integrations/google_ads/presenters/report"

import { cases, entry, envelope, fileId } from "./result-preview-fixtures"

describe("retained report presentation", () => {
  it("renders BigQuery previews inside the query card with complete-result access", () => {
    const preview = {
      ...envelope("bigquery", {}),
      data: {
        rows: Array.from({ length: 50 }, (_, index) => ({ campaign: `Campaign ${String(index)}` })),
        total_rows: 1500,
        total_bytes_processed: 4096,
        truncated: false,
        cache_hit: true,
        row_filters_applied: true,
      },
      lists: { rows: { shown: 50, total: 1500 } },
    }
    const html = render(bigQueryQueryPresenter, preview)
    expect(html).toContain("Preview: 50 of 1,500 returned rows.")
    expect(html).toMatch(
      /<section[^>]*aria-label="BigQuery query results"[\s\S]*Open complete result[\s\S]*<\/section>/
    )
    const complete = {
      ...preview.data,
      rows: Array.from({ length: 1500 }, () => ({ campaign: "Saved result" })),
    }
    const completeHtml = render(bigQueryQueryPresenter, complete, preview)
    expect(completeHtml).toContain("1,500 of 1,500 returned rows.")
    expect(completeHtml).not.toContain("Open complete result")
  })

  it.each(cases)(
    "renders $provider $presenter.key previews with pagination and an inline complete-result control",
    ({ presenter, provider, data }) => {
      const html = render(presenter, envelope(provider, data))
      expect(html).toContain("Preview: 50 of 1,000 returned rows.")
      expect(html).not.toContain(`/files?fileId=${fileId}`)
      expect(html).toMatch(
        /<section[^>]*aria-label="Website"[\s\S]*Open complete result[\s\S]*<\/section>/
      )
    }
  )

  it("keeps complete public rows with the retained counts without labelling them a preview", () => {
    const preview = envelope("google_ads", cases[0]?.data)
    const complete = {
      results: [
        entry("google_ads", {
          ...cases[0]?.data,
          rows: Array.from({ length: 1000 }, () => ({
            campaign: { name: "Full public row" },
            metrics: { clicks: 7 },
          })),
        }),
      ],
    }
    preview.lists["results.0.data.rows"] = { shown: 50, total: 1000 }
    const html = render(googleAdsReportPresenter, complete, preview)
    expect(html).toContain("Full public row")
    expect(html).not.toContain("Country 0")
    expect(html).not.toContain("Open complete result")
    expect(html).toContain("1,000 of 1,000 returned rows.")
    expect(html).not.toContain("Preview:")
  })

  it.each([
    { file_id: "javascript:alert(1)" },
    { lists: { "results.0.data.rows": { shown: 51, total: 1000 } } },
    { lists: { "__proto__.rows": { shown: 50, total: 1000 } } },
  ])("rejects malformed retained references or counts: %j", (override) => {
    const preview = { ...envelope("google_ads", cases[0]?.data), ...override }
    expect(parseResultPreview(preview)).toBeNull()
    expect(render(googleAdsReportPresenter, preview)).toBe("<div></div>")
  })
})

function render(presenter: ToolRowPresenter, result: unknown, resultPreview?: unknown) {
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: new QueryClient() },
      createElement(
        "div",
        null,
        presenter.render({
          activity: {
            id: "report",
            kind: "result",
            name: presenter.key,
            status: "completed",
            result,
            resultPreview,
          },
          compact: false,
          defaultOpen: true,
          live: false,
          providerKey: null,
        })
      )
    )
  )
}
