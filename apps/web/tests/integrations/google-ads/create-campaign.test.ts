// apps/web/tests/integrations/google-ads/create-campaign.test.ts

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import {
  campaignAdGroupRows,
  campaignProblems,
  canCheckCampaign,
  createCampaignBlock,
  parseCreateCampaignArgs,
  serializeCampaign,
  type CreateCampaignArgs,
} from "@/integrations/google_ads/lib/create-campaign"
import { googleAdsCreateCampaignPresenter } from "@/integrations/google_ads/presenters/create-campaign"

const CUSTOMER = "1234567890"

const ad = {
  headlines: [{ text: "Hiking Boots" }, { text: "Free Returns" }, { text: "Waterproof" }],
  descriptions: [{ text: "Boots for every trail." }, { text: "Free UK delivery." }],
  final_url: "https://shop.test/boots",
}

function group(over: Record<string, unknown> = {}) {
  return {
    name: "Waterproof Boots",
    keywords: [{ text: "waterproof hiking boots", match_type: "EXACT" }],
    ads: [ad],
    ...over,
  }
}

function campaign(over: Record<string, unknown> = {}) {
  return {
    name: "Hiking Boots UK",
    budget: { kind: "new", daily_amount: "60" },
    bidding: { strategy: "MAXIMIZE_CONVERSIONS", target_cpa: "18.00" },
    locations: [{ key: "2826", name: "United Kingdom" }],
    ...over,
  }
}

function args(over: Record<string, unknown> = {}, checks: Record<string, unknown> = {}) {
  return {
    campaign: campaign(),
    ad_groups: [group()],
    status: "PAUSED",
    _accounts: [
      { customer_id: CUSTOMER, name: "Northwind", currency: "GBP", time_zone: "Europe/London" },
    ],
    _checks: {
      unavailable: false,
      today: "2026-11-09",
      strategy_name: "Maximise Conversions",
      locations: { "2826": "United Kingdom" },
      unknown_locations: [],
      campaign_problems: [],
      problems: [],
      request_problems: [],
      ...checks,
    },
    ...over,
  }
}

function parsed(value: unknown): CreateCampaignArgs {
  const result = parseCreateCampaignArgs(value)
  if (!result) throw new Error("expected create campaign args")
  return result
}

function groupProblems(value: unknown): string[] | undefined {
  return campaignAdGroupRows(parsed(value))[0]?.problems
}

describe("Google Ads create campaign arguments", () => {
  it("holds ad group bids to the new campaign's own bidding", () => {
    expect(groupProblems(args({ ad_groups: [group({ cpc_bid: "0.90" })] }))).toEqual([
      "Has a £0.90 click bid, but the campaign uses Maximise Conversions. Remove the bid to continue.",
    ])
    const manual = campaign({ bidding: { strategy: "MANUAL_CPC" } })
    expect(
      groupProblems(args({ campaign: manual, ad_groups: [group({ cpc_bid: "0.90" })] }))
    ).toEqual([])
    // A target CPA override needs the campaign to set one first.
    const noTarget = campaign({ bidding: { strategy: "MAXIMIZE_CONVERSIONS" } })
    expect(
      groupProblems(args({ campaign: noTarget, ad_groups: [group({ target_cpa: "20" })] }))
    ).toHaveLength(1)
  })

  it("blocks an ad group that couldn't serve and a campaign with no location", () => {
    expect(groupProblems(args({ ad_groups: [group({ keywords: [], ads: [] })] }))).toEqual([
      "Needs at least 1 keyword to serve.",
      "Needs at least 1 ad to serve.",
    ])
    const nowhere = parsed(args({ campaign: campaign({ locations: [] }) }))
    expect(campaignProblems(nowhere)).toEqual([
      "Choose at least one location, so the ads don't show everywhere.",
    ])
    expect(createCampaignBlock(nowhere, nowhere)).toBe("Fix the campaign settings to continue.")
  })

  it("names locations Google doesn't know and applies its rejections only while they're there", () => {
    const value = args(
      {
        campaign: campaign({
          locations: [{ key: "2826" }, { key: "1006886", name: "London" }, { key: "999" }],
        }),
      },
      {
        unknown_locations: ["999"],
        campaign_problems: [
          { kind: "location", key: "1006886", message: "Google says: Can't target this." },
        ],
      }
    )
    expect(campaignProblems(parsed(value))).toEqual([
      "Google doesn't recognise Location 999. Remove it.",
      "London: Google says: Can't target this.",
    ])
    const removed = { ...value, campaign: campaign({ locations: [{ key: "2826" }] }) }
    expect(campaignProblems(parsed(removed))).toEqual([])
  })

  it("makes approval wait on a check after a settings edit, but not after a status edit", () => {
    const checked = parsed(args())
    expect(createCampaignBlock(parsed(args({ status: "ENABLED" })), checked)).toBeNull()

    const edited = parsed(args({ campaign: campaign({ search_partners: true }) }))
    expect(canCheckCampaign(edited)).toBe(true)
    expect(createCampaignBlock(edited, checked)).toBe(
      "Click Check Changes so Google can check your edits, then approve."
    )

    // The card can already see a past start date, so asking Google can wait.
    const past = parsed(args({ campaign: campaign({ start_date: "2026-11-01" }) }))
    expect(canCheckCampaign(past)).toBe(false)
  })

  it("sends only the chosen strategy's fields and a ROAS percentage as a ratio", () => {
    const draft = parsed(args()).campaign
    const value = serializeCampaign({
      ...draft,
      bidding: { ...draft.bidding, strategy: "MAXIMIZE_CONVERSION_VALUE", targetRoas: "350" },
    })
    expect(value["bidding"]).toEqual({ strategy: "MAXIMIZE_CONVERSION_VALUE", target_roas: 3.5 })
    expect(value).toMatchObject({ start_date: null, end_date: null, search_partners: false })
    expect(parsed(args({ campaign: value })).campaign.bidding.targetRoas).toBe("350")
  })
})

describe("Google Ads create campaign card", () => {
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

  it("renders the approval with its monthly spend and the created kinds", () => {
    const approval = html(
      googleAdsCreateCampaignPresenter.render(
        baseProps(
          {
            id: "campaign-1",
            kind: "approval",
            name: "google_ads_create_campaign",
            status: "awaiting_approval",
            args: args({ ad_groups: [group(), group({ name: "Leather Boots" })] }),
          },
          true
        )
      )
    )
    expect(approval).toContain("£1,824.00")

    const result = html(
      googleAdsCreateCampaignPresenter.render(
        baseProps({
          id: "campaign-2",
          kind: "result",
          name: "google_ads_create_campaign",
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
                  campaign_name: "Hiking Boots UK",
                  requested_status: "PAUSED",
                  outcome: "created",
                  campaign: null,
                  kinds: [
                    { kind: "campaign", created: 1, failed: 0, unverified: 0 },
                    { kind: "keyword", created: 912, failed: 0, unverified: 0 },
                  ],
                  ad_groups: [],
                  problems: [],
                },
              },
            ],
          },
        })
      )
    )
    expect(result).toContain("913 created, paused")
  })
})
