// apps/web/tests/integrations/google-ads/update-ads.test.ts

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import {
  adRows,
  editsFor,
  mergedCopy,
  parseUpdateAdsArgs,
  updateAdsBlock,
  withEdits,
  type LiveCopy,
  type UpdateAdsArgs,
} from "@/integrations/google_ads/lib/update-ads"
import { googleAdsUpdateAdsPresenter } from "@/integrations/google_ads/presenters/update-ads"

const CUSTOMER = "1234567890"
const key = (id: string) => `customers/${CUSTOMER}/adGroupAds/20~${id}`

function ad(id: string) {
  return { customer_id: CUSTOMER, campaign_id: "10", ad_group_id: "20", ad_id: id, label: "Ad" }
}

const current = {
  headlines: [
    { text: "Trail Running Shoes", pin: "HEADLINE_1" },
    { text: "Shop the Range", pin: null },
    { text: "Next-Day Delivery", pin: null },
  ],
  descriptions: [
    { text: "Grippy trail shoes.", pin: null },
    { text: "Order by 8pm.", pin: null },
  ],
  path1: "trail",
  path2: null,
  final_url: "https://northwind.example/trail",
}

const swap = {
  remove_headlines: ["Shop the Range"],
  add_headlines: [{ text: "Free Returns on Every Order" }],
}

function check(over: Record<string, unknown> = {}) {
  return {
    unavailable: false,
    name: "Trail Running Shoes",
    ad_group_name: "Women's Trail Shoes",
    campaign_name: "Trail Running",
    current,
    requested: { ...swap, add_headlines: [{ text: "Free Returns on Every Order", pin: null }] },
    problem: null,
    problems: [],
    ...over,
  }
}

function raw(ids: string[] = ["30"], over: Record<string, unknown> = {}) {
  return {
    changes: ids.map((id) => ({ ad: ad(id), ...swap })),
    _accounts: [
      { customer_id: CUSTOMER, name: "Northwind", currency: "GBP", time_zone: "Europe/London" },
    ],
    _checks: Object.fromEntries(ids.map((id) => [key(id), check()])),
    ...over,
  }
}

function parsed(value: unknown = raw()): UpdateAdsArgs {
  const args = parseUpdateAdsArgs(value)
  if (args === null) throw new Error("Expected valid args")
  return args
}

function live(): LiveCopy {
  const copy = parseUpdateAdsArgs(raw())?.checks.get(key("30"))
  if (!copy || copy.unavailable || !copy.current) throw new Error("Expected live copy")
  return copy.current
}

describe("merge", () => {
  it("puts an added headline in the removed one's place", () => {
    const { after, problems } = mergedCopy(live(), {
      remove_headlines: ["Shop the Range"],
      add_headlines: [{ text: "Free Returns", pin: "HEADLINE_2" }],
    })
    expect(after.headlines.map((item) => [item.text, item.pin])).toEqual([
      ["Trail Running Shoes", "HEADLINE_1"],
      ["Free Returns", "HEADLINE_2"],
      ["Next-Day Delivery", null],
    ])
    expect(problems).toEqual([])
  })

  it("refuses a removal that leaves two headlines on the card, before any check", () => {
    const args = parsed(
      raw(["30"], { changes: [{ ad: ad("30"), remove_headlines: ["Shop the Range"] }] })
    )
    expect(adRows(args, args)[0]?.problems).toEqual([
      "An ad needs 3 to 15 headlines. This edit leaves 2.",
    ])
  })

  it("writes an editor change back as edits that merge to the same copy, pin kept", () => {
    const copy = live()
    const wanted = {
      ...copy,
      headlines: copy.headlines.map((item, at) =>
        at === 0 ? { ...item, text: "Trail Shoes" } : item
      ),
      path1: null,
    }
    const edits = editsFor(copy, wanted)

    expect(edits).toEqual({
      add_headlines: [{ text: "Trail Shoes", pin: "HEADLINE_1" }],
      remove_headlines: ["Trail Running Shoes"],
      path1: "",
    })
    expect(mergedCopy(copy, edits).after).toEqual(wanted)
  })
})

describe("approval", () => {
  it("holds Google's problem to the edits it checked, and an edit waits for a new check", () => {
    const checked = parsed(
      raw(["30"], { _checks: { [key("30")]: check({ problem: "Google says: Trademark." }) } })
    )
    expect(updateAdsBlock(checked, checked)).toBe("Fix or cancel 1 ad to continue.")

    const [change] = checked.changes
    if (!change) throw new Error("Expected a change")
    const next = parsed({
      ...raw(),
      changes: [withEdits(change.entry, { ...change.edits, path2: "shoes" })],
      _checks: { [key("30")]: check({ problem: "Google says: Trademark." }) },
    })
    expect(updateAdsBlock(next, checked)).toBe(
      "Click Check Changes so Google can check your edits, then approve."
    )
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

  it("renders a shared swap and the result", () => {
    const approval = html(
      googleAdsUpdateAdsPresenter.render(
        props(
          {
            id: "ads-1",
            kind: "approval",
            name: "google_ads_update_ads",
            status: "awaiting_approval",
            args: raw(["30", "31"]),
          },
          true
        )
      )
    )
    expect(approval).toContain("Free Returns on Every Order")

    const result = html(
      googleAdsUpdateAdsPresenter.render(
        props({
          id: "ads-2",
          kind: "result",
          name: "google_ads_update_ads",
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
                  ads: [
                    {
                      resource_name: key("30"),
                      ad_id: "30",
                      name: "Trail Running Shoes",
                      ad_group_name: "Women's Trail Shoes",
                      campaign_name: "Trail Running",
                      before: current,
                      requested: null,
                      after: {
                        ...current,
                        headlines: [
                          current.headlines[0],
                          { text: "Free Returns on Every Order", pin: null },
                          current.headlines[2],
                        ],
                      },
                      outcome: "updated",
                      review_status: "REVIEW_IN_PROGRESS",
                      approval_status: "UNKNOWN",
                    },
                  ],
                },
              },
            ],
          },
        })
      )
    )
    expect(result).toContain("In Review")
  })
})
