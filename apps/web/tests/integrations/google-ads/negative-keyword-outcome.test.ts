import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import {
  CampaignNegativeKeywordOutcome,
  AdGroupNegativeKeywordOutcome,
} from "@/integrations/google_ads/components/negative-keyword-outcome"

const totals = { applied: 2, skipped: 1, failed: 1 }
const evidence = {
  counts: totals,
  errors: [
    { text: "free", matchType: "EXACT" as const, errorCode: "TARGET_CPA", message: "Rejected bid" },
  ],
  errorsTruncated: true,
  keywordOutcomes: null,
}

describe("Google Ads scoped negative keyword outcomes", () => {
  it.each(["add", "remove"] as const)(
    "preserves legacy aggregate %s evidence without inventing keyword rows",
    (action) => {
      const results = [
        createElement(CampaignNegativeKeywordOutcome, {
          action,
          result: {
            totals,
            campaignsTruncated: false,
            campaigns: [{ ...evidence, campaignId: "10", campaignName: "Search" }],
          },
        }),
        createElement(AdGroupNegativeKeywordOutcome, {
          action,
          result: {
            totals,
            adGroupsTruncated: false,
            adGroups: [
              { ...evidence, adGroupId: "20", adGroupName: "Shoes", campaignName: "Search" },
            ],
          },
        }),
      ]
      for (const result of results) {
        const html = renderToStaticMarkup(result)
        expect(html).toContain("Search")
        expect(html).toContain(action === "add" ? "Added" : "Removed")
        expect(html).toContain(action === "add" ? "Already existed" : "Not found")
        expect(html).toContain("Rejected bid")
        expect(html).toContain("Target CPA")
        expect(html).toContain("Download Report CSV")
        expect(html).not.toContain(">Keyword<")
        expect(html).not.toContain(">free<")
        expect(html).toContain(
          "Showing a representative sample. Complete evidence is in the Audit Log."
        )
        const cells = (html.match(/<td[\s\S]*?<\/td>/g) ?? []).map((cell) =>
          cell.replace(/<[^>]*>/g, "")
        )
        expect(cells.filter((cell) => cell === "2")).toHaveLength(1)
        expect(cells.filter((cell) => cell === "1")).toHaveLength(2)
      }
    }
  )
})
