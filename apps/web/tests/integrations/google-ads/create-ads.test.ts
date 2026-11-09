// apps/web/tests/integrations/google-ads/create-ads.test.ts

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import {
  adRows,
  createAdsApproveLabel,
  createAdsBlock,
  parseCreateAdsArgs,
  previewAssets,
  serializeAds,
  HEADLINE_PINS,
  type CreateAdsArgs,
} from "@/integrations/google_ads/lib/create-ads"
import { googleAdsCreateAdsPresenter } from "@/integrations/google_ads/presenters/create-ads"

const CUSTOMER = "1234567890"
const GROUP_20 = `customers/${CUSTOMER}/adGroups/20`
const GROUP_21 = `customers/${CUSTOMER}/adGroups/21`

function adGroup(id: string) {
  return {
    entity_kind: "google_ads_ad_group",
    customer_id: CUSTOMER,
    campaign_id: "10",
    ad_group_id: id,
    label: `Group ${id}`,
  }
}

const copy = {
  headlines: [
    { text: "Trail Shoes", pin: "HEADLINE_1" },
    { text: "Free Returns" },
    { text: "Grip" },
  ],
  descriptions: [{ text: "Lightweight trail shoes." }, { text: "Free UK delivery." }],
  final_url: "https://example.com/trail",
  path1: "trail",
}

function args(over: Record<string, unknown> = {}) {
  return {
    ads: [{ ...copy, ad_groups: [adGroup("20"), adGroup("21")] }],
    status: "PAUSED",
    _accounts: [
      { customer_id: CUSTOMER, name: "Northwind", currency: "GBP", time_zone: "Europe/London" },
    ],
    _checks: {
      unavailable: false,
      ad_groups: {
        [GROUP_20]: { name: "Men's Trail", campaign_name: "Trail", problem: null },
        [GROUP_21]: { name: "Women's Trail", campaign_name: "Trail", problem: null },
      },
      ads: [
        {
          ad: { ...copy, mobile_final_url: null, path2: null },
          problems: [{ ad_group: GROUP_21, message: "Google says: Trademark in headline 1." }],
        },
      ],
      problems: [],
    },
    ...over,
  }
}

function parsed(value: unknown = args()): CreateAdsArgs {
  const result = parseCreateAdsArgs(value)
  if (!result) throw new Error("expected create ads args")
  return result
}

describe("Google Ads create ads arguments", () => {
  it("applies Google's rejection to the copy it checked and drops it once the copy changes", () => {
    const original = parsed()
    expect(adRows(original)[0]?.problems).toEqual([
      "Women's Trail: Google says: Trademark in headline 1.",
    ])

    const ad = original.ads[0]
    if (!ad) throw new Error("expected an ad")
    const edited = parsed({
      ...args(),
      ads: serializeAds([
        { ...ad, headlines: [...ad.headlines.slice(1), { pin: null, text: "Run" }] },
      ]),
    })
    expect(adRows(edited)[0]?.problems).toEqual([])
    expect(createAdsApproveLabel(edited)).toBe("Create 2 Ads")
  })

  it("blocks approval for a 31-character headline and a path 2 without a path 1", () => {
    const value = args({
      ads: [
        {
          ...copy,
          headlines: [{ text: "Grip Any Trail. Free Returns Now" }, ...copy.headlines.slice(1)],
          path1: "",
          path2: "sale",
          ad_groups: [adGroup("20")],
        },
      ],
    })
    expect(adRows(parsed(value))[0]?.problems).toEqual([
      "Headline 1 is 32 characters. The limit is 30.",
      "Fill in path 1 before path 2.",
    ])
    expect(createAdsBlock(parsed(value))).toBe("Fix or cancel 1 ad to continue.")
  })

  it("keeps each reference whole and sends blank optional fields as null", () => {
    const [ad] = serializeAds(parsed().ads)
    expect(ad).toMatchObject({
      ad_groups: [adGroup("20"), adGroup("21")],
      mobile_final_url: null,
      path2: null,
      headlines: [
        { text: "Trail Shoes", pin: "HEADLINE_1" },
        { text: "Free Returns" },
        { text: "Grip" },
      ],
    })
  })

  it("previews pinned headlines in their place and fills the rest in order", () => {
    const assets = [
      { text: "A", pin: null },
      { text: "B", pin: "HEADLINE_2" },
      { text: "C", pin: null },
    ]
    expect(previewAssets(assets, HEADLINE_PINS)).toEqual(["A", "B", "C"])
  })
})

describe("Google Ads create ads card", () => {
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

  it("renders the approval preview and the created ads with their review state", () => {
    const approval = html(
      googleAdsCreateAdsPresenter.render(
        baseProps(
          {
            id: "ads-1",
            kind: "approval",
            name: "google_ads_create_ads",
            status: "awaiting_approval",
            args: args(),
          },
          true
        )
      )
    )
    expect(approval).toContain("https://example.com/trail")

    const result = html(
      googleAdsCreateAdsPresenter.render(
        baseProps({
          id: "ads-2",
          kind: "result",
          name: "google_ads_create_ads",
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
                  requested_status: "PAUSED",
                  ads: [
                    {
                      ad: 1,
                      ad_group: GROUP_20,
                      ad_group_name: "Men's Trail",
                      campaign_name: "Trail",
                      headline: "Trail Shoes",
                      resource_name: `customers/${CUSTOMER}/adGroupAds/20~900`,
                      outcome: "created",
                      status: "PAUSED",
                      review_status: "REVIEW_IN_PROGRESS",
                      approval_status: null,
                      error_code: null,
                      message: null,
                    },
                  ],
                },
              },
            ],
          },
        })
      )
    )
    expect(result).toContain("Under Review")
  })
})
