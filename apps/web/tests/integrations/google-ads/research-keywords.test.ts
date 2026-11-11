// apps/web/tests/integrations/google-ads/research-keywords.test.ts

import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import {
  buildAdGroupInstruction,
  parseKeywordResearch,
  themeTabs,
} from "@/integrations/google_ads/lib/research-keywords"
import { googleAdsResearchKeywordsPresenter } from "@/integrations/google_ads/presenters/research-keywords"

const DATA = {
  account_id: "4821930571",
  currency: "GBP",
  locations: [{ key: "2826", name: "United Kingdom" }],
  language: { key: "1000", name: "English" },
  total_ideas: 2400,
  truncated: true,
  ad_groups: [{ ad_group_id: "20", campaign_id: "10", name: "Trail Shoes", usable: true }],
  ideas: [
    {
      text: "trail running shoes",
      requested: false,
      avg_monthly_searches: 22200,
      competition: "HIGH",
      low_bid: "0.58",
      high_bid: "1.42",
      trend: [100, 140, 120],
      themes: ["Trail", "Running"],
      close_variants: [],
      ad_group_id: "20",
      match_type: "PHRASE",
    },
    {
      text: "waterproof trail shoes",
      requested: false,
      avg_monthly_searches: 6600,
      competition: "MEDIUM",
      low_bid: "0.47",
      high_bid: "1.10",
      trend: [],
      themes: ["Trail", "Waterproof"],
      close_variants: [],
      ad_group_id: null,
      match_type: null,
    },
    {
      text: "fell shoes",
      requested: true,
      avg_monthly_searches: null,
      competition: null,
      low_bid: null,
      high_bid: null,
      trend: [],
      themes: [],
      close_variants: [],
      ad_group_id: null,
      match_type: null,
    },
  ],
}

describe("Google Ads keyword research", () => {
  it("renders the ideas with bids in the account currency and a trend line", () => {
    const html = renderToStaticMarkup(
      createElement(
        "div",
        null,
        googleAdsResearchKeywordsPresenter.render({
          activity: {
            id: "research-1",
            kind: "result",
            name: "google_ads_research_keywords",
            status: "completed",
            args: { seeds: ["running shoes"] },
            result: {
              results: [
                {
                  provider_key: "google_ads",
                  display_name: "Northwind",
                  external_id: "4821930571",
                  status: "success",
                  data: DATA,
                  error_message: null,
                },
              ],
            },
          },
          compact: false,
          defaultOpen: true,
          live: false,
          providerKey: "google_ads",
        })
      )
    )

    expect(html).toContain("£1.42")
    expect(html).toContain('aria-label="12-Month Trend: 100 to 120"')
  })

  it("refuses a result whose idea has an unknown competition level", () => {
    const [idea] = DATA.ideas
    expect(parseKeywordResearch({ ...DATA, ideas: [{ ...idea, competition: "EXTREME" }] })).toBe(
      null
    )
  })

  it("makes tabs of the commonest themes, with the rest under Other Themes", () => {
    const result = parseKeywordResearch(DATA)
    if (!result) throw new Error("expected a result")
    const tabs = themeTabs(result.ideas)
    const rows = result.ideas.map((idea) => ({ themes: idea.themes }))

    expect(tabs.map((tab) => tab.label)).toEqual([
      "All",
      "Trail",
      "Running",
      "Waterproof",
      "Other Themes",
    ])
    expect(rows.filter((row) => tabs[4]?.match(row))).toHaveLength(1)
  })

  it("asks for one ad group from the chosen keywords, without names the agent supplied", () => {
    const result = parseKeywordResearch(DATA)
    if (!result) throw new Error("expected a result")

    const [first, second] = result.ideas
    if (!first || !second) throw new Error("expected two ideas")
    const instruction = buildAdGroupInstruction(result, [
      { ...first, text: "trail  running\nshoes" },
      second,
    ])

    expect(instruction.split("\n").slice(1)).toEqual([
      "- trail running shoes (Google suggests phrase match)",
      "- waterproof trail shoes",
    ])
    expect(instruction).toContain("482-193-0571")
  })
})
