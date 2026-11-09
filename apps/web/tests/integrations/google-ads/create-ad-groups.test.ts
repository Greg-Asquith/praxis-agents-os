// apps/web/tests/integrations/google-ads/create-ad-groups.test.ts

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import { formatKeywordLine, parseKeywordLines } from "@/integrations/ads/lib/keyword-notation"
import {
  adGroupRows,
  canCheckAdGroups,
  createAdGroupsApproveLabel,
  createAdGroupsBlock,
  mergePastedKeywords,
  parseCreateAdGroupsArgs,
  serializeAdGroups,
  type CreateAdGroupsArgs,
} from "@/integrations/google_ads/lib/create-ad-groups"
import { googleAdsCreateAdGroupsPresenter } from "@/integrations/google_ads/presenters/create-ad-groups"

const CUSTOMER = "1234567890"
const CAMPAIGN_KEY = `customers/${CUSTOMER}/campaigns/10`

const ad = {
  headlines: [{ text: "Trail Shoes" }, { text: "Free Returns" }, { text: "Grip" }],
  descriptions: [{ text: "Lightweight trail shoes." }, { text: "Free UK delivery." }],
  final_url: "https://shop.test/trail",
}

function group(over: Record<string, unknown> = {}) {
  return {
    name: "Wide Fit",
    keywords: [{ text: "wide trail shoes", match_type: "PHRASE" }],
    negative_keywords: [{ text: "cheap", match_type: "BROAD" }],
    ads: [ad],
    ...over,
  }
}

function checks(over: Record<string, unknown> = {}) {
  return {
    unavailable: false,
    campaign: {
      key: CAMPAIGN_KEY,
      name: "Trail",
      strategy: "MAXIMIZE_CONVERSIONS",
      strategy_name: "Maximise Conversions",
      accepts_cpc_bid: false,
      accepts_target_cpa: true,
      accepts_target_roas: false,
      problem: null,
    },
    existing_names: ["Trail Shoes"],
    problems: [],
    request_problems: [],
    ...over,
  }
}

function args(ad_groups: unknown[] = [group()], over: Record<string, unknown> = {}) {
  return {
    campaign: {
      entity_kind: "google_ads_campaign",
      customer_id: CUSTOMER,
      campaign_id: "10",
      label: "Trail",
    },
    ad_groups,
    status: "PAUSED",
    _accounts: [
      { customer_id: CUSTOMER, name: "Northwind", currency: "GBP", time_zone: "Europe/London" },
    ],
    _checks: checks(),
    ...over,
  }
}

function parsed(value: unknown): CreateAdGroupsArgs {
  const result = parseCreateAdGroupsArgs(value)
  if (!result) throw new Error("expected create ad groups args")
  return result
}

function problems(value: unknown): string[] | undefined {
  return adGroupRows(parsed(value))[0]?.problems
}

describe("keyword notation", () => {
  it("reads Google's notation and writes it back", () => {
    const keywords = parseKeywordLines('[trail shoes]\n"fell  runners"\n\n  gore-tex boots  ')
    expect(keywords).toEqual([
      { matchType: "EXACT", text: "trail shoes" },
      { matchType: "PHRASE", text: "fell runners" },
      { matchType: "BROAD", text: "gore-tex boots" },
    ])
    expect(keywords.map(formatKeywordLine)).toEqual([
      "[trail shoes]",
      '"fell runners"',
      "gore-tex boots",
    ])
  })

  it("keeps a keyword's bid when a paste keeps the keyword and drops it when the match changes", () => {
    const current = [
      { cpcBid: "0.90", finalUrl: "", matchType: "PHRASE" as const, text: "trail shoes" },
    ]
    expect(
      mergePastedKeywords(parseKeywordLines('"Trail Shoes"\n[trail shoes]'), current).map(
        (keyword) => keyword.cpcBid
      )
    ).toEqual(["0.90", ""])
  })
})

describe("Google Ads create ad groups arguments", () => {
  it("blocks a click bid the campaign's bidding ignores and names the strategy", () => {
    const value = args([group({ cpc_bid: "0.90" })])
    expect(problems(value)).toEqual([
      "Has a £0.90 click bid, but the campaign uses Maximise Conversions. Remove the bid to continue.",
    ])
    expect(createAdGroupsBlock(parsed(value), parsed(value))).toBe(
      "Fix or cancel 1 ad group to continue."
    )
  })

  it("blocks keyword bids under the same rule, and lets them through under manual bidding", () => {
    const keywords = [{ text: "wide trail shoes", match_type: "PHRASE", cpc_bid: "0.90" }]
    const refused = args([group({ keywords })])
    expect(problems(refused)?.[0]).toContain("Has keyword click bids")

    const campaign = { ...checks().campaign, accepts_cpc_bid: true }
    expect(problems(args([group({ keywords })], { _checks: checks({ campaign }) }))).toEqual([])
  })

  it("treats a live name in any case as taken, and two new ad groups with one name as a clash", () => {
    expect(problems(args([group({ name: "trail  shoes" })]))).toEqual([
      "Trail already has an ad group with this name.",
    ])
    expect(problems(args([group(), group({ name: "WIDE FIT" })]))).toEqual([
      "Another new ad group has this name.",
    ])
  })

  it("stops applying the campaign's rules once another campaign is chosen", () => {
    const value = args([group({ cpc_bid: "0.90", name: "Trail Shoes" })], {
      campaign: { customer_id: CUSTOMER, campaign_id: "11", label: "Other" },
    })
    expect(problems(value)).toEqual([])
  })

  it("applies Google's rejection only while the rejected keyword is still there", () => {
    const rejected = checks({
      problems: [
        {
          ad_group: "Wide Fit",
          kind: "keyword",
          text: "wide trail shoes",
          match_type: "PHRASE",
          message: "Google says: Symbol not allowed.",
        },
      ],
    })
    expect(problems(args([group()], { _checks: rejected }))).toEqual([
      "wide trail shoes: Google says: Symbol not allowed.",
    ])
    const edited = group({ keywords: [{ text: "wide shoes", match_type: "PHRASE" }] })
    expect(problems(args([edited], { _checks: rejected }))).toEqual([])
  })

  it("names the ad a copy problem is in", () => {
    const short = { ...ad, headlines: [{ text: "Trail Shoes" }] }
    expect(problems(args([group({ ads: [ad, short] })]))).toEqual([
      "Ad 2: Add at least 3 headlines. This ad has 1.",
    ])
  })

  it("blocks approval when the campaign isn't usable, and counts ad groups on the button", () => {
    const blocked = args([group()], {
      _checks: checks({
        campaign: { ...checks().campaign, problem: "New ad groups only go in Search campaigns." },
      }),
    })
    expect(createAdGroupsBlock(parsed(blocked), parsed(blocked))).toBe(
      "New ad groups only go in Search campaigns."
    )
    expect(createAdGroupsApproveLabel(parsed(args([group(), group({ name: "B" })])))).toBe(
      "Create 2 Ad Groups"
    )
  })

  it("makes approval wait on a check once the campaign or an ad group changes", () => {
    const checked = parsed(args())
    expect(createAdGroupsBlock(parsed(args([group()], { status: "ENABLED" })), checked)).toBeNull()

    const moved = args([group()], {
      campaign: { customer_id: CUSTOMER, campaign_id: "11", label: "Other" },
    })
    expect(canCheckAdGroups(parsed(moved))).toBe(true)
    expect(createAdGroupsBlock(parsed(moved), checked)).toBe("Check the changes before approving.")

    const renamed = args([group({ name: "Narrow Fit" })])
    expect(createAdGroupsBlock(parsed(renamed), checked)).toBe(
      "Check the changes before approving."
    )

    // The card already knows this campaign ignores click bids, so asking Google can wait.
    expect(canCheckAdGroups(parsed(args([group({ cpc_bid: "0.90" })])))).toBe(false)
  })

  it("sends a ROAS percentage as a ratio and survives a round trip", () => {
    const [draft] = parsed(args([group({ target_roas: 3.5 })])).adGroups
    if (!draft) throw new Error("expected an ad group")
    expect(draft.targetRoas).toBe("350")
    const [sent] = serializeAdGroups([{ ...draft, targetRoas: "420.5" }])
    expect(sent).toMatchObject({ target_roas: 4.205, cpc_bid: null })
    expect(parsed(args([sent])).adGroups[0]?.targetRoas).toBe("420.5")
  })
})

describe("Google Ads create ad groups card", () => {
  const baseProps = (activity: ToolActivity, withApproval = false) => ({
    activity,
    ...(withApproval
      ? {
          approvalDecision: {
            decision: { decision: "pending" as const, edits: {}, message: "" as const },
            error: null,
            onDecisionChange: vi.fn(),
            onRetry: vi.fn(),
            pendingCount: 1,
            submitting: false,
          },
        }
      : {}),
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "google_ads",
  })
  const html = (node: ReactNode) =>
    renderToStaticMarkup(
      createElement(
        QueryClientProvider,
        { client: new QueryClient() },
        createElement("div", null, node)
      )
    )

  it("renders the approval and the created kinds", () => {
    const approval = html(
      googleAdsCreateAdGroupsPresenter.render(
        baseProps(
          {
            id: "groups-1",
            kind: "approval",
            name: "google_ads_create_ad_groups",
            status: "awaiting_approval",
            args: args([group(), group({ name: "Sale" })]),
          },
          true
        )
      )
    )
    expect(approval).toContain("Campaign Uses Maximise Conversions")

    const result = html(
      googleAdsCreateAdGroupsPresenter.render(
        baseProps({
          id: "groups-2",
          kind: "result",
          name: "google_ads_create_ad_groups",
          status: "completed",
          args: args(),
          result: {
            results: [
              {
                provider_key: "google_ads",
                display_name: "Northwind",
                external_id: CUSTOMER,
                status: "success",
                data: {
                  account_id: CUSTOMER,
                  campaign_name: "Trail",
                  requested_status: "PAUSED",
                  kinds: [{ kind: "keyword", created: 1140, failed: 0, unverified: 0 }],
                  ad_groups: [],
                  problems: [],
                },
              },
            ],
          },
        })
      )
    )
    expect(result).toContain("1,140 created, paused")
  })
})
