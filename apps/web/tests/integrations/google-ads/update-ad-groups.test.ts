// apps/web/tests/integrations/google-ads/update-ad-groups.test.ts

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import {
  addableSettings,
  addedAdGroupChanges,
  adGroupRows,
  adGroupsApproveLabel,
  adGroupsBlock,
  editedAdGroupChanges,
  parseUpdateAdGroupsArgs,
  restoredAdGroupChanges,
  scaledMoney,
  type UpdateAdGroupsArgs,
} from "@/integrations/google_ads/lib/update-ad-groups"
import { googleAdsUpdateAdGroupsPresenter } from "@/integrations/google_ads/presenters/update-ad-groups"

const CUSTOMER = "1234567890"
const key = (id: string) => `customers/${CUSTOMER}/adGroups/${id}`
const NOT_USED =
  "Waterproof Range uses Maximise Conversions, so Google doesn't use an ad group CPC bid."

function adGroup(id: string) {
  return { customer_id: CUSTOMER, campaign_id: "10", ad_group_id: id, label: `Ad Group ${id}` }
}

function check(over: Record<string, unknown> = {}) {
  return {
    unavailable: false,
    name: "Waterproof Shoes",
    campaign_name: "Waterproof Range",
    strategy_name: "Maximise Conversions",
    bids_used: ["target_cpa"],
    current: { cpc_bid: "1.1", target_cpa: "12" },
    requested: { cpc_bid: "1.21", target_cpa: null },
    problem: null,
    problems: { cpc_bid: NOT_USED },
    ...over,
  }
}

function raw(over: Record<string, unknown> = {}) {
  return {
    changes: [{ ad_group: adGroup("1"), cpc_bid: "1.21", target_cpa: "none" }],
    _accounts: [
      { customer_id: CUSTOMER, name: "Northwind", currency: "GBP", time_zone: "Europe/London" },
    ],
    _checks: { [key("1")]: check() },
    ...over,
  }
}

function parsed(value: unknown = raw()): UpdateAdGroupsArgs {
  const args = parseUpdateAdGroupsArgs(value)
  if (args === null) throw new Error("Expected valid args")
  return args
}

describe("approval", () => {
  it("holds the strategy problem to the bid Google checked, and an edit waits for a new check", () => {
    const checked = parsed()
    expect(adGroupRows(checked, checked).map((row) => row.problem)).toEqual([NOT_USED, null])
    expect(adGroupsBlock(checked, checked)).toBe("Fix or cancel 1 change to continue.")

    const next = parsed({
      ...raw(),
      changes: editedAdGroupChanges(checked, new Set([`${key("1")}|cpc_bid`]), () => "0.9"),
    })

    expect(adGroupRows(next, checked)[0]?.problem).toBeNull()
    expect(adGroupsBlock(next, checked)).toBe(
      "Click Check Changes so Google can check your edits, then approve."
    )
  })

  it("writes a removed target as none and URL settings inside url_options", () => {
    const args = parsed(raw({ changes: [{ ad_group: adGroup("1"), target_roas: 4 }] }))
    const ids = new Set([`${key("1")}|target_roas`])

    expect(editedAdGroupChanges(args, ids, () => null)).toEqual([
      { ad_group: adGroup("1"), target_roas: "none" },
    ])
    const removal = raw({
      changes: [{ ad_group: adGroup("1"), target_roas: "none" }],
      _checks: { [key("1")]: check({ current: { target_roas: 3.5 } }) },
    })
    expect(adGroupsApproveLabel(parsed(removal))).toBe("Remove Target ROAS")

    // Undo puts a cancelled URL setting back where the tool reads it, with an empty value clearing it.
    expect(
      restoredAdGroupChanges(parsed(raw({ changes: [] })), [
        { adGroup: adGroup("1"), key: key("1"), setting: "final_url_suffix", value: null },
      ])
    ).toEqual([{ ad_group: adGroup("1"), url_options: { final_url_suffix: "" } }])
  })

  it("offers settings the agent didn't propose, from their live values, and only usable bids", () => {
    const args = parsed(
      raw({
        changes: [{ ad_group: adGroup("1"), target_cpa: "none" }],
        _checks: {
          [key("1")]: check({ current: { name: "Waterproof Shoes", target_cpa: "12" } }),
        },
      })
    )
    const options = addableSettings(args, adGroupRows(args, args), key("1"))

    // The campaign uses Maximise Conversions, so it offers no CPC bid or target ROAS.
    expect(options.map((item) => item.setting)).toEqual([
      "name",
      "final_url_suffix",
      "tracking_template",
      "custom_parameters",
      "ad_rotation",
    ])
    expect(options.find((item) => item.setting === "ad_rotation")?.value).toBe("OPTIMIZE")
    expect(addedAdGroupChanges(args, key("1"), "name", "Waterproof Boots")).toEqual([
      { ad_group: adGroup("1"), target_cpa: "none", name: "Waterproof Boots" },
    ])
  })

  it("changes bids by a percentage in the currency's smallest unit", () => {
    expect(scaledMoney("0.78", 10, "GBP")).toBe("0.86")
    expect(scaledMoney("120", 10, "JPY")).toBe("132")
    // A cut never reaches zero, which Google refuses.
    expect(scaledMoney("0.01", -90, "GBP")).toBe("0.01")
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
      googleAdsUpdateAdGroupsPresenter.render(
        props(
          {
            id: "ad-groups-1",
            kind: "approval",
            name: "google_ads_update_ad_groups",
            status: "awaiting_approval",
            args: raw(),
          },
          true
        )
      )
    )
    expect(approval).toContain("Waterproof Range uses Maximise Conversions")

    const result = html(
      googleAdsUpdateAdGroupsPresenter.render(
        props({
          id: "ad-groups-2",
          kind: "result",
          name: "google_ads_update_ad_groups",
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
                  currency: "GBP",
                  ad_groups: [
                    {
                      resource_name: key("1"),
                      ad_group_id: "1",
                      name: "Waterproof Shoes",
                      campaign_name: "Waterproof Range",
                      read_back: true,
                      settings: [
                        {
                          setting: "target_cpa",
                          before: "12",
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
    expect(result).toContain("Campaign&#x27;s target")
  })
})
