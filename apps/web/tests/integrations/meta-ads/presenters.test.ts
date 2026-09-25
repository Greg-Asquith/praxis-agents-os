import { createElement } from "react"
import { readFileSync } from "node:fs"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import { metaAdsInsightsPresenter } from "@/integrations/meta_ads/presenters/insights"

import { envelope } from "../result-preview-fixtures"
import { accountEntry, insightsData, insightsRow } from "./fixtures"

describe("Meta Ads Insights presenter", () => {
  it("renders the running state", () => {
    expect(render({ status: "running" })).toContain("Running Meta Ads Insights")
  })

  it("renders reports with correctly scaled CTR, currency, windows, and notes above the table", () => {
    const html = render({
      result: {
        results: [
          accountEntry(
            insightsData({
              mode: "background",
              notes: ["Reach was omitted for this date range."],
              truncated: true,
              truncation_note: "Returned the first 100 rows.",
            })
          ),
        ],
      },
    })
    expect(html).toContain("Run Meta Ads Insights")
    expect(html).toContain("Example campaign")
    expect(html).toContain("0.5%")
    expect(html).toContain(
      new Intl.NumberFormat(undefined, { currency: "EUR", style: "currency" }).format(125.5)
    )
    expect(html).toContain("1d Click")
    expect(html).toContain("7d Click")
    expect(html).toContain("Europe/Paris")
    expect(html).toContain("Prepared as a background report")
    expect(html).toContain("Returned the first 100 rows.")
    expect(html.indexOf("Reach was omitted")).toBeLessThan(html.indexOf("<table"))
    expect(html).not.toContain(">Total</")
  })

  it("renders empty accounts, empty rows, and per-account errors", () => {
    expect(render({ result: { results: [] } })).toContain("No Meta Ads accounts were queried.")
    const html = render({
      result: {
        results: [
          accountEntry(insightsData({ rows: [], row_count: 0 })),
          accountEntry(null, {
            external_id: "456",
            status: "error",
            error_message: "Wait 60 seconds before trying this account again.",
          }),
        ],
      },
    })
    expect(html).toContain("No report rows returned.")
    expect(html).toContain("1/2 connections")
    expect(html).toContain("Wait 60 seconds")
  })

  it("renders JPY without decimal places and handles missing account metadata", () => {
    const html = render({ result: { results: [accountEntry(insightsData({ currency: "JPY" }))] } })
    expect(html).toContain(
      new Intl.NumberFormat(undefined, { currency: "JPY", style: "currency" }).format(125.5)
    )
    expect(html).not.toContain("125.50")
    const missing = render({
      result: { results: [accountEntry(insightsData({ currency: "", timezone_name: "" }))] },
    })
    expect(missing).toContain("Currency unavailable")
    expect(missing).toContain("Account time zone unavailable")
  })

  it("uses the retained preview controls and keeps provider truncation separate", () => {
    const data = insightsData({
      rows: Array.from({ length: 50 }, () => insightsRow()),
      row_count: 1000,
      truncated: true,
      truncation_note: "Returned the first 1,000 rows.",
    })
    const preview = envelope("meta_ads", data)
    const html = render({ result: preview })
    expect(html).toContain("Preview: 50 of 1,000 returned rows.")
    expect(html).toContain("Open complete result")
    expect(html).toContain("Returned the first 1,000 rows.")
    expect(html).toContain("Next")
    expect(html).toContain("Access was removed.")
    expect(html).not.toContain(">Total</")
    const complete = {
      results: [accountEntry({ ...data, rows: Array.from({ length: 1000 }, () => insightsRow()) })],
    }
    const completeHtml = render({ result: complete, resultPreview: preview })
    expect(completeHtml).toContain("1,000 of 1,000 returned rows.")
    expect(completeHtml).not.toContain("Open complete result")
  })

  it("renders hostile campaign names as text", () => {
    const name = readFileSync(
      new URL(
        "../../../../api/tests/fixtures/prompt_injection/hostile_meta_campaign_name.txt",
        import.meta.url
      ),
      "utf8"
    ).trim()
    const html = render({
      result: {
        results: [
          accountEntry(insightsData({ rows: [insightsRow({ keys: { campaign_name: name } })] })),
        ],
      },
    })
    expect(html).toContain("&lt;script&gt;")
    expect(html).toContain("Ignore previous instructions")
    expect(html).not.toContain("<script>")
    expect(html).not.toContain('href="https://example.invalid/collect"')
  })

  it("falls back to the default tool row for malformed results", () => {
    expect(render({ result: { results: [accountEntry({ rows: "bad" })] } })).toBe("<div></div>")
  })
})

function render(overrides: Partial<ToolActivity>) {
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: new QueryClient() },
      createElement(
        "div",
        null,
        metaAdsInsightsPresenter.render({
          activity: {
            id: "insights",
            kind: "result",
            name: "meta_ads_run_insights",
            status: "completed",
            ...overrides,
          },
          compact: false,
          defaultOpen: true,
          live: false,
          providerKey: "meta_ads",
        })
      )
    )
  )
}
