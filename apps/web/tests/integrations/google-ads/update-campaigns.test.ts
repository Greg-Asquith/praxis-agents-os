// apps/web/tests/integrations/google-ads/update-campaigns.test.ts

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import { parseBidding } from "@/integrations/google_ads/lib/campaign-bidding"
import {
  addableCampaignSettings,
  addedCampaignChanges,
  campaignCounts,
  campaignRows,
  campaignsApproveLabel,
  campaignsBlock,
  editedChanges,
  parseCancelled,
  parseUpdateCampaignsArgs,
  restoredChanges,
  type UpdateCampaignsArgs,
} from "@/integrations/google_ads/lib/update-campaigns"
import { googleAdsUpdateCampaignsPresenter } from "@/integrations/google_ads/presenters/update-campaigns"

const CUSTOMER = "1234567890"
const key = (id: string) => `customers/${CUSTOMER}/campaigns/${id}`

function campaign(id: string) {
  return { customer_id: CUSTOMER, campaign_id: id, label: `Campaign ${id}` }
}

function check(over: Record<string, unknown> = {}) {
  return {
    unavailable: false,
    name: "Trail",
    current: { name: "Trail", end_date: "2026-12-31", search_partners: true },
    requested: { end_date: null, search_partners: false },
    problem: null,
    problems: {},
    ...over,
  }
}

function raw(over: Record<string, unknown> = {}) {
  return {
    changes: [{ campaign: campaign("10"), end_date: "none", networks: { search_partners: false } }],
    _accounts: [
      { customer_id: CUSTOMER, name: "Northwind", currency: "GBP", time_zone: "Europe/London" },
    ],
    _checks: { [key("10")]: check() },
    ...over,
  }
}

function parsed(value: unknown = raw()): UpdateCampaignsArgs {
  const args = parseUpdateCampaignsArgs(value)
  if (args === null) throw new Error("Expected valid args")
  return args
}

function edited(changes: unknown[]): UpdateCampaignsArgs {
  return parsed({ ...raw(), changes })
}

describe("approval", () => {
  it("holds a problem to the value Google checked, and an edit waits for a new check", () => {
    const checked = parsed(
      raw({ _checks: { [key("10")]: check({ problems: { end_date: "Choose a later date." } }) } })
    )
    expect(campaignsBlock(checked, checked)).toBe("Fix or cancel 1 change to continue.")

    const ids = new Set([`${key("10")}|end_date`])
    const next = edited(editedChanges(checked, ids, () => "2027-01-31"))

    expect(campaignRows(next, checked).map((row) => row.problem)).toEqual([null, null])
    expect(campaignsBlock(next, checked)).toBe(
      "Click Check Changes so Google can check your edits, then approve."
    )
  })

  it("takes a campaign out when every setting is cancelled, and Undo brings it back", () => {
    const args = parsed()
    const ids = new Set([`${key("10")}|end_date`, `${key("10")}|search_partners`])

    expect(editedChanges(args, ids, () => undefined)).toEqual([])

    const restored = restoredChanges(edited([]), [
      { campaign: campaign("10"), key: key("10"), setting: "end_date", value: null },
    ])
    expect(restored).toEqual([{ campaign: campaign("10"), end_date: "none" }])
  })

  it("doesn't count a setting already at its value, and names a sole change on the button", () => {
    const args = parsed(
      raw({ changes: [{ campaign: campaign("10"), networks: { search_partners: true } }] })
    )
    expect(campaignCounts(campaignRows(args, args)).apply).toBe(0)

    const removal = parsed(raw({ changes: [{ campaign: campaign("10"), end_date: "none" }] }))
    expect(campaignsApproveLabel(removal)).toBe("Remove End Date")
  })
})

describe("adding a change", () => {
  it("offers what the channel and campaign allow, from live values", () => {
    const current = {
      name: "Trail",
      start_date: "2026-01-01",
      end_date: null,
      search_partners: true,
      display_expansion: false,
      bidding: { strategy: "PORTFOLIO", portfolio: "customers/1/biddingStrategies/5" },
    }
    const args = parsed(
      raw({
        changes: [
          { campaign: campaign("10"), name: "Trail Shoes" },
          { campaign: campaign("11"), name: "Banners" },
        ],
        _checks: {
          [key("10")]: check({ channel: "SEARCH", current, requested: { name: "Trail Shoes" } }),
          [key("11")]: check({
            channel: "DISPLAY",
            current: { ...current, bidding: { strategy: "MANUAL_CPC" } },
            requested: { name: "Banners" },
          }),
        },
      })
    )
    const rows = campaignRows(args, args)
    const offered = (id: string) =>
      addableCampaignSettings(args, args, rows, key(id)).map((item) => item.setting)

    // Started campaigns can't move their start; a portfolio can't be written back as is.
    expect(offered("10")).toEqual([
      "end_date",
      "final_url_suffix",
      "tracking_template",
      "custom_parameters",
      "search_partners",
      "display_expansion",
    ])
    // Display campaigns change no networks here.
    expect(offered("11")).toEqual([
      "end_date",
      "final_url_suffix",
      "tracking_template",
      "custom_parameters",
      "bidding",
    ])
    expect(addedCampaignChanges(args, key("11"), "end_date", null)[1]).toEqual({
      campaign: campaign("11"),
      name: "Banners",
      end_date: "none",
    })
  })
})

describe("bidding", () => {
  const strategy = (id: string, current: unknown, requested: unknown, over = {}) => ({
    [key(id)]: check({ current: { bidding: current }, requested: { bidding: requested }, ...over }),
  })
  const smart = { strategy: "MAXIMIZE_CONVERSIONS", target_cpa: "15" }

  it("resolves a target change against the live strategy, and counts learning for a new one", () => {
    const args = parsed(
      raw({
        changes: [
          { campaign: campaign("10"), bidding: { strategy: "TARGETS", target_cpa: "15.00" } },
          {
            campaign: campaign("11"),
            bidding: { strategy: "MAXIMIZE_CONVERSIONS", target_cpa: "18.00" },
          },
          { campaign: campaign("12"), bidding: { strategy: "TARGETS", target_roas: 4 } },
        ],
        _checks: {
          ...strategy("10", smart, { strategy: "TARGETS", target_cpa: "15" }),
          // The server writes money canonically, so "18.00" is the value it checked.
          ...strategy(
            "11",
            { strategy: "MANUAL_CPC" },
            { strategy: "MAXIMIZE_CONVERSIONS", target_cpa: "18" },
            { problems: { bidding: "Google says: no conversion tracking." } }
          ),
          // A target the live strategy can't take changes nothing, so it isn't Already Set.
          ...strategy(
            "12",
            { strategy: "MAXIMIZE_CLICKS", max_cpc: null },
            {
              strategy: "TARGETS",
              target_roas: 4,
            }
          ),
        },
      })
    )
    const rows = campaignRows(args, args)

    expect(rows.map((row) => [row.unchanged, row.learning, row.problem])).toEqual([
      [true, false, null],
      [false, true, "Google says: no conversion tracking."],
      [false, false, null],
    ])
    expect(campaignCounts(rows).learning).toBe(1)
  })

  it("writes an edited strategy as the tool argument, keeping a portfolio's reference", () => {
    const args = parsed(
      raw({
        changes: [{ campaign: campaign("10"), bidding: { strategy: "MANUAL_CPC" } }],
        _checks: strategy("10", smart, { strategy: "MANUAL_CPC" }),
      })
    )
    const ids = new Set([`${key("10")}|bidding`])
    const portfolio = { customer_id: CUSTOMER, bidding_strategy_id: "5", label: "Brand tCPA" }

    const toPortfolio = editedChanges(args, ids, () =>
      parseBidding({ strategy: "PORTFOLIO", portfolio })
    )
    const toClicks = editedChanges(args, ids, () =>
      parseBidding({ strategy: "MAXIMIZE_CLICKS", max_cpc: null })
    )

    expect(toPortfolio[0]?.["bidding"]).toEqual({ strategy: "PORTFOLIO", portfolio })
    expect(toClicks[0]?.["bidding"]).toEqual({ strategy: "MAXIMIZE_CLICKS" })

    // A cancelled portfolio change is read again from the card's own record before Undo.
    const value = parseBidding({ strategy: "PORTFOLIO", portfolio })
    const held = parseCancelled([
      { campaign: campaign("10"), key: key("10"), setting: "bidding", value },
    ])
    expect(restoredChanges(edited([]), held)).toEqual([
      { campaign: campaign("10"), bidding: { strategy: "PORTFOLIO", portfolio } },
    ])
  })
})

describe("presenters", () => {
  const html = (node: ReactNode) =>
    renderToStaticMarkup(
      createElement(
        QueryClientProvider,
        { client: new QueryClient() },
        createElement("div", null, node)
      )
    )
  const props = (activity: ToolActivity, withApproval = false) => ({
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

  it("renders the approval and the result", () => {
    const approval = html(
      googleAdsUpdateCampaignsPresenter.render(
        props(
          {
            id: "campaigns-1",
            kind: "approval",
            name: "google_ads_update_campaigns",
            status: "awaiting_approval",
            args: raw({
              changes: [
                ...raw().changes,
                {
                  campaign: campaign("11"),
                  bidding: { strategy: "MAXIMIZE_CONVERSIONS", target_cpa: "18" },
                },
              ],
              _checks: {
                [key("10")]: check(),
                [key("11")]: check({
                  current: { bidding: { strategy: "MANUAL_CPC" } },
                  requested: { bidding: { strategy: "MAXIMIZE_CONVERSIONS", target_cpa: "18" } },
                }),
              },
            }),
          },
          true
        )
      )
    )
    expect(approval).toContain("31 Dec 2026")

    const result = html(
      googleAdsUpdateCampaignsPresenter.render(
        props({
          id: "campaigns-2",
          kind: "result",
          name: "google_ads_update_campaigns",
          status: "completed",
          args: raw(),
          result: {
            results: [
              {
                provider_key: "google_ads",
                display_name: "Northwind",
                external_id: CUSTOMER,
                status: "success",
                data: {
                  account_id: CUSTOMER,
                  campaigns: [
                    {
                      resource_name: key("10"),
                      campaign_id: "10",
                      name: "Trail",
                      read_back: true,
                      settings: [
                        {
                          setting: "end_date",
                          before: "2026-12-31",
                          requested: null,
                          after: null,
                          outcome: "updated",
                        },
                      ],
                    },
                  ],
                },
              },
            ],
          },
        })
      )
    )
    expect(result).toContain("No end date")
  })
})
