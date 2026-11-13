// apps/web/tests/integrations/google-ads/create-asset-groups.test.ts

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import {
  createAssetGroupRows,
  createAssetGroupsBlock,
  parseCreateAssetGroupsArgs,
  type CreateAssetGroupsArgs,
} from "@/integrations/google_ads/lib/create-asset-groups"
import { serializeAssetGroups } from "@/integrations/google_ads/lib/performance-max"
import { googleAdsCreateAssetGroupsPresenter } from "@/integrations/google_ads/presenters/create-asset-groups"

const CUSTOMER = "1234567890"

function image(assetId: string, fieldType: string) {
  return {
    asset: {
      customer_id: CUSTOMER,
      asset_id: assetId,
      asset_type: "IMAGE",
      label: `Image ${assetId}`,
    },
    field_type: fieldType,
  }
}

function assetGroup(over: Record<string, unknown> = {}) {
  return {
    name: "Rain Jackets",
    final_url: "https://shop.test/rain-jackets",
    headlines: ["Rain Jackets", "Stay Dry Outside", "Free Returns"],
    long_headlines: ["Waterproof jackets for every trail"],
    descriptions: ["Light, packable, and fully taped.", "Free UK delivery."],
    images: [image("301", "MARKETING_IMAGE"), image("302", "SQUARE_MARKETING_IMAGE")],
    search_themes: ["waterproof jacket"],
    audience_signals: [{ kind: "user_list", key: "401", name: "Buyers" }],
    ...over,
  }
}

function args(groups: unknown[] = [assetGroup()], checks: Record<string, unknown> = {}) {
  return {
    campaign: { customer_id: CUSTOMER, campaign_id: "10", label: "PMax Hiking" },
    asset_groups: groups,
    status: "PAUSED",
    _accounts: [
      { customer_id: CUSTOMER, name: "Northwind", currency: "GBP", time_zone: "Europe/London" },
    ],
    _checks: {
      unavailable: false,
      campaign: {
        key: `customers/${CUSTOMER}/campaigns/10`,
        name: "PMax Hiking UK",
        retail: false,
        problem: null,
      },
      existing_names: ["Boots"],
      images: {
        "301": { name: "Jacket", width: 1200, height: 628, fits: ["MARKETING_IMAGE"] },
        "302": { name: "Square", width: 1200, height: 1200, fits: ["SQUARE_MARKETING_IMAGE"] },
      },
      unknown_images: [],
      audiences: { "user_list:401": "Past Buyers" },
      unknown_audiences: [],
      problems: [],
      request_problems: [],
      ...checks,
    },
  }
}

function parsed(value: unknown): CreateAssetGroupsArgs {
  const result = parseCreateAssetGroupsArgs(value)
  if (!result) throw new Error("expected create asset groups args")
  return result
}

describe("Google Ads add asset groups arguments", () => {
  it("blocks a name the campaign already uses and an audience the account doesn't have", () => {
    const value = parsed(
      args(
        [
          assetGroup({ name: "boots" }),
          assetGroup({
            name: "Fleeces",
            audience_signals: [{ kind: "user_list", key: "999", name: "Old List" }],
          }),
        ],
        { unknown_audiences: ["user_list:999"] }
      )
    )
    expect(createAssetGroupRows(value).map((row) => row.problems)).toEqual([
      ["The campaign already has an asset group by this name."],
      ["Old List isn't an audience in this account. Remove it."],
    ])
    expect(createAssetGroupsBlock(value, value)).toBe("Fix or cancel 2 asset groups to continue.")
  })

  it("keeps Google's signal rejection only while the group still has a signal", () => {
    const rejected = {
      problems: [
        {
          asset_group: "Rain Jackets",
          kind: "audience",
          content: null,
          message: "Google says: This list can't be used.",
        },
      ],
    }
    expect(createAssetGroupRows(parsed(args(undefined, rejected)))[0]?.problems).toEqual([
      "Google says: This list can't be used.",
    ])
    const removed = parsed(args([assetGroup({ audience_signals: [] })], rejected))
    expect(createAssetGroupRows(removed)[0]?.problems).toEqual([])
  })

  it("sends only the URL options a new group has", () => {
    const options = { final_url_suffix: " utm_source=google ", tracking_template: "" }
    const groups = parsed(args([assetGroup({ url_options: options }), assetGroup()])).assetGroups
    const [tracked, plain] = serializeAssetGroups(groups)

    expect(tracked?.["url_options"]).toEqual({ final_url_suffix: "utm_source=google" })
    expect(plain).not.toHaveProperty("url_options")
  })

  it("sends each audience signal with its kind and key", () => {
    expect(serializeAssetGroups(parsed(args()).assetGroups)[0]?.["audience_signals"]).toEqual([
      { kind: "user_list", key: "401", name: "Buyers" },
    ])
  })
})

describe("Google Ads add asset groups card", () => {
  it("renders the approval with the campaign first and its audience signal", () => {
    const html = renderToStaticMarkup(
      createElement(
        QueryClientProvider,
        { client: new QueryClient() },
        googleAdsCreateAssetGroupsPresenter.render({
          activity: {
            id: "asset-groups-1",
            kind: "approval",
            name: "google_ads_create_asset_groups",
            status: "awaiting_approval",
            args: args(),
          },
          approvalDecision: {
            decision: { decision: "pending", edits: {}, message: "" },
            error: null,
            onDecisionChange: vi.fn(),
            onRetry: vi.fn(),
            pendingCount: 1,
            submitting: false,
          },
          compact: false,
          defaultOpen: true,
          live: false,
          providerKey: "google_ads",
        })
      )
    )
    expect(html).toContain("PMax Hiking UK")
    expect(html).toContain("Add 1 Asset Group")
  })
})
