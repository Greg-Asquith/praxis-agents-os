import { createElement } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { parseResultPreview } from "@/components/tool-ui/result-preview"
import type { ToolRowPresenter } from "@/integrations/contract"
import { bigQueryQueryPresenter } from "@/integrations/bigquery/presenters/query"
import { googleAdsReportFieldsPresenter } from "@/integrations/google_ads/presenters/report-fields"
import { googleAdsReportPresenter } from "@/integrations/google_ads/presenters/report"
import { googleAnalyticsReportPresenter } from "@/integrations/google_analytics/presenters/report"
import { googleAnalyticsReportFieldsPresenter } from "@/integrations/google_analytics/presenters/report-fields"

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
    expect(html).toContain("Campaign 0")
    expect(html).not.toContain("Campaign 49</")
    expect(html).toContain("Next")
    expect(html).toContain("Row filters limited this result to allowed values.")
    const complete = {
      ...preview.data,
      rows: Array.from({ length: 1500 }, () => ({ campaign: "Saved result" })),
    }
    const completeHtml = render(bigQueryQueryPresenter, complete, preview)
    expect(completeHtml).toContain("1,500 of 1,500 returned rows.")
    expect(completeHtml).not.toContain("Open complete result")
  })

  it("loads the complete Ads field catalogue in its existing tool card", () => {
    const field = {
      name: "campaign.name",
      category: "ATTRIBUTE",
      data_type: "STRING",
      selectable: true,
      filterable: true,
      sortable: true,
      is_repeated: false,
    }
    const preview = {
      ...envelope("google_ads", {}),
      data: {
        api_version: "v24",
        resource: "campaign",
        search_matched: true,
        fields: Array.from({ length: 50 }, () => field),
        field_count: 1500,
        metrics: [],
        metric_count: 0,
        segments: [],
        segment_count: 0,
        attribute_resources: [],
        attribute_resource_count: 0,
        compatibility_truncated: false,
        truncated: false,
      },
      lists: { fields: { shown: 50, total: 1500 } },
    }
    const html = render(
      googleAdsReportFieldsPresenter,
      preview,
      undefined,
      "google_ads_list_report_fields"
    )
    expect(html).toContain("Fields: Preview: 50 of 1,500 returned fields.")
    expect(html).toMatch(
      /<section[^>]*aria-label="Google Ads report fields"[\s\S]*Open complete result[\s\S]*<\/section>/
    )
    expect(html).toContain("campaign.name")
    expect(html).toContain("Next")
    const complete = { ...preview.data, fields: Array.from({ length: 1500 }, () => field) }
    const completeHtml = render(
      googleAdsReportFieldsPresenter,
      complete,
      preview,
      "google_ads_list_report_fields"
    )
    expect(completeHtml).toContain("1,500 of 1,500 returned fields.")
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
      expect(html).toContain("Country 0")
      expect(html).not.toContain("Country 49</")
      expect(html).toContain("Next")
      expect(html).toContain("Access was removed.")
      if (provider === "google_ads") expect(html).not.toContain(">Total</")
      if (presenter === googleAnalyticsReportPresenter) {
        expect(html).toContain("999,999")
        expect(html).toContain("privacy thresholds")
        expect(html).toContain("50 of 2,000 rows shown")
      } else if (provider !== "google_analytics") {
        expect(html).toContain("Provider returned 1,000 rows.")
      }
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
    expect(html).toContain("Next")
    expect(html).toContain(">Total</")
  })

  it("shows separate dimension and metric preview counts", () => {
    const field = {
      api_name: "country",
      ui_name: "Country",
      description: "Location",
      category: "User",
      custom: false,
    }
    const preview = envelope("google_analytics", {
      dimensions: [field],
      metrics: [{ ...field, api_name: "sessions", type: "TYPE_INTEGER", blocked_reasons: [] }],
      dimension_count: 100,
      metric_count: 200,
      truncated: false,
    })
    preview.lists = {
      "results.0.data.dimensions": { shown: 1, total: 100 },
      "results.0.data.metrics": { shown: 1, total: 200 },
    }
    const html = render(googleAnalyticsReportFieldsPresenter, preview)
    expect(html).toContain("Dimensions: Preview: 1 of 100 returned dimensions.")
    expect(html).toContain("Metrics: Preview: 1 of 200 returned metrics.")
    expect(html).toContain("Open complete result")
  })

  it.each([
    { file_id: "javascript:alert(1)" },
    { file_reference: { version: 1, entity_kind: "artifact", entity_id: fileId } },
    { lists: { "results.0.data.rows": { shown: 51, total: 1000 } } },
    { lists: { "results.0.data.rows": { shown: 50, total: 1 } } },
    { lists: { "__proto__.rows": { shown: 50, total: 1000 } } },
  ])("rejects malformed retained references or counts: %j", (override) => {
    const preview = { ...envelope("google_ads", cases[0]?.data), ...override }
    expect(parseResultPreview(preview)).toBeNull()
    expect(render(googleAdsReportPresenter, preview)).toBe("<div></div>")
  })
})

function render(
  presenter: ToolRowPresenter,
  result: unknown,
  resultPreview?: unknown,
  name = presenter.key
) {
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
            name,
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
