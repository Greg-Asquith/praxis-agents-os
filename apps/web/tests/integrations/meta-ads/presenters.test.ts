import { createElement } from "react"
import { readFileSync } from "node:fs"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import { metaAdsInsightsPresenter } from "@/integrations/meta_ads/presenters/insights"

import { accountEntry, insightsData, insightsRow } from "./fixtures"

describe("Meta Ads Insights presenter", () => {
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
    expect(html).toContain("0.5%")
    expect(html).toContain(
      new Intl.NumberFormat(undefined, { currency: "EUR", style: "currency" }).format(125.5)
    )
    expect(html.indexOf("Reach was omitted")).toBeLessThan(html.indexOf("<table"))
    expect(html).not.toContain(">Total</")
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
