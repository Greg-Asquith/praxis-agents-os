import { createElement, useState, type ReactNode } from "react"
import type * as ReactModule from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { afterEach, describe, expect, it, vi } from "vitest"

import { MetaAdsInsightsResults } from "@/integrations/meta_ads/components/insights-results"
import { parseMetaAdsInsights } from "@/integrations/meta_ads/lib/insights-model"

import { insightsData, insightsRow } from "./fixtures"

vi.mock("react", async (original) => {
  const module = await original<typeof ReactModule>()
  return { ...module, useState: vi.fn(module.useState) }
})
vi.mock("@/hooks/use-clipboard-copy", () => ({
  useClipboardCopy: () => ({ copied: false, copy: vi.fn() }),
}))
vi.mock("@/components/ui/sheet", () => {
  const element = ({ children }: { children?: ReactNode }) => createElement("div", null, children)
  return {
    Sheet: ({ children, open }: { children?: ReactNode; open: boolean }) =>
      open ? createElement("aside", null, children) : null,
    SheetContent: element,
    SheetDescription: element,
    SheetHeader: element,
    SheetTitle: element,
  }
})

afterEach(() => vi.clearAllMocks())

describe("Meta Ads Insights row details", () => {
  it.each(["EUR", "JPY", ""])(
    "uses the same currency, CTR, and ROAS formatting in cells and details for %j",
    (currency) => {
      const report = parseMetaAdsInsights(
        insightsData({
          currency,
          rows: [
            insightsRow({
              metrics: { social_spend: 125.5, ctr: 0.5 },
              actions: {
                purchase_roas: [{ action_type: "purchase", value: 2.5, windows: {} }],
              },
            }),
          ],
        })
      )
      if (!report) throw new Error("Invalid fixture")
      vi.mocked(useState).mockImplementationOnce(() => [report.rows[0], vi.fn()])
      const html = renderToStaticMarkup(
        createElement(MetaAdsInsightsResults, { report, externalId: "123" })
      )
      const table = html.slice(html.indexOf("<table"), html.indexOf("</table>"))
      const details = html.slice(html.indexOf("<aside"), html.indexOf("</aside>"))
      const money = currency
        ? new Intl.NumberFormat(undefined, { style: "currency", currency }).format(125.5)
        : "125.5"
      for (const section of [table, details]) {
        expect(section).toContain("Social Spend")
        expect(section).toContain(money)
        expect(section).toContain("0.5%")
        expect(section).toContain(">2.5<")
        expect(section).not.toContain("2.5%")
      }
      expect(details).toContain("Report row details")
      if (!currency) expect(html).toContain("Currency unavailable")
    }
  )
})
