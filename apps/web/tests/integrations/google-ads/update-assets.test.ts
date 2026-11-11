// apps/web/tests/integrations/google-ads/update-assets.test.ts

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { restoreParent, restoreRow } from "@/integrations/ads/lib/cancelled-rows"
import type { ToolActivity } from "@/integrations/contract"
import { fieldProblem, newAssetKey } from "@/integrations/google_ads/lib/new-assets"
import {
  addTarget,
  ASSET_CANCEL_CARD,
  assetsBlock,
  cancelLinks,
  canCheckAssets,
  editNewAsset,
  linkRows,
  needsCheck,
  newAssetRows,
  parseUpdateAssetsArgs,
  sitelinksAfter,
  type UpdateAssetsArgs,
} from "@/integrations/google_ads/lib/update-assets"
import { googleAdsUpdateAssetsPresenter } from "@/integrations/google_ads/presenters/update-assets"

const CUSTOMER = "1234567890"
const C = `customers/${CUSTOMER}`

const SITELINK = {
  type: "sitelink",
  link_text: "Size  Guide",
  description1: "Find your size",
  description2: "Fit tips",
  final_url: "https://shop.example/size",
}
const SITELINK_KEY = "new|sitelink|Size Guide|Find your size|Fit tips|https://shop.example/size||"
const SALE = { customer_id: CUSTOMER, asset_id: "70", asset_type: "SITELINK", label: "Sale" }
const PRICE = {
  type: "price",
  price_type: "SERVICES",
  currency_code: "gbp",
  offerings: [0, 1, 2].map((at) => ({
    header: `Tier ${String(at)}`,
    description: "Per pair",
    price: "9.99",
    unit: at === 0 ? "PER_MONTH" : null,
    final_url: "https://shop.example/t",
  })),
}

function campaign(id: string, label: string) {
  return { customer_id: CUSTOMER, campaign_id: id, label }
}

function check(name: string, sitelinks: number, rows: Record<string, unknown>[]) {
  return {
    unavailable: false,
    name,
    problem: null,
    now: { SITELINK: sitelinks, CALLOUT: 0 },
    rows,
  }
}

function raw() {
  return {
    entries: [
      {
        kind: "campaign",
        campaign: campaign("10", "Trail"),
        add: [SITELINK],
        remove: [SALE],
      },
      { kind: "campaign", campaign: campaign("20", "Road"), add: [SITELINK] },
    ],
    _accounts: [
      { customer_id: CUSTOMER, name: "Northwind", currency: "GBP", time_zone: "Europe/London" },
    ],
    _checks: {
      [`${C}/campaigns/10`]: check("Trail", 2, [
        { row: "asset:70", action: "remove", state: "change", problem: null, label: "Sale" },
        { row: SITELINK_KEY, action: "add", state: "change", problem: null },
      ]),
      [`${C}/campaigns/20`]: check("Road", 5, [
        { row: SITELINK_KEY, action: "add", state: "already_set", problem: null },
      ]),
    },
  }
}

function args(value: unknown = raw()): UpdateAssetsArgs {
  const parsed = parseUpdateAssetsArgs(value)
  if (parsed === null) throw new Error("expected valid args")
  return parsed
}

describe("update assets", () => {
  it("names a new asset as the server does, collapsing spaces and keeping a date's day", () => {
    expect(newAssetKey(SITELINK)).toBe(SITELINK_KEY)
    expect(newAssetKey({ type: "callout", text: "Sale", start_date: "2026-12-01T00:00:00" })).toBe(
      "new|callout|Sale|2026-12-01|"
    )
  })

  it("names snippets, calls, and prices as the server does after it tidies them", () => {
    expect(
      newAssetKey({
        type: "structured_snippet",
        header: "brands",
        values: ["Trail  Co", "Peak", "Ridge"],
      })
    ).toBe("new|structured_snippet|Brands|Trail Co|Peak|Ridge")
    expect(
      newAssetKey({ type: "call", country_code: "gb", phone_number: "+44 (20) 7946-0000" })
    ).toBe("new|call|GB|+442079460000")
    expect(newAssetKey(PRICE)).toBe(
      "new|price|SERVICES||en|GBP|" +
        [0, 1, 2]
          .map(
            (at) =>
              `Tier ${String(at)}|Per pair|9.99|${at === 0 ? "PER_MONTH" : ""}|https://shop.example/t`
          )
          .join("|")
    )
  })

  it("blocks a snippet with too many values, a price with too few items, and a foreign phone format", () => {
    const values = Array.from({ length: 11 }, (_, at) => `Brand ${String(at)}`)
    expect(fieldProblem({ type: "structured_snippet", header: "Brands", values })).toBe(
      "Values: add 3 to 10, separated by commas."
    )
    expect(fieldProblem({ ...PRICE, offerings: PRICE.offerings.slice(0, 2) })).toBe(
      "A price needs 3 to 8 items."
    )
    expect(fieldProblem({ type: "call", country_code: "GB", phone_number: "020 7946 ext 1" })).toBe(
      "Enter a phone number of 6 to 16 digits."
    )
    expect(fieldProblem(PRICE)).toBeNull()
  })

  it("shows a new asset once, and an edit changes it in every target and asks for a check", () => {
    const checked = args()
    const rows = linkRows(checked, checked)
    expect(newAssetRows(rows, checked)).toEqual([
      expect.objectContaining({ key: SITELINK_KEY, targets: 2 }),
    ])
    expect(assetsBlock(checked, checked)).toBeNull()

    const { entries } = editNewAsset(checked, [], SITELINK_KEY, "link_text", "Find Your Size")
    expect(entries.map((entry) => entry.add[0]?.value["link_text"])).toEqual([
      "Find Your Size",
      "Find Your Size",
    ])
    expect(needsCheck({ ...checked, entries }, checked)).toBe(true)
  })

  it("leaves one asset when an edit makes two the same, and a cancelled link follows the edit", () => {
    const other = { ...SITELINK, link_text: "Fit Guide" }
    const value = raw()
    value.entries[0]?.add.push(other)
    const checked = args(value)
    const road = linkRows(checked, checked).find((row) => row.targetName === "Road")
    if (!road) throw new Error("expected Road's link")

    const edit = editNewAsset(checked, [road], SITELINK_KEY, "link_text", "Fit Guide")
    expect(edit.entries[0]?.add.map((item) => item.key)).toEqual([newAssetKey(other)])
    expect(edit.rows.map((row) => [row.assetKey, row.value["link_text"]])).toEqual([
      [newAssetKey(other), "Fit Guide"],
    ])
  })

  it("blocks a field over Google's limit and a sitelink with one description line", () => {
    expect(fieldProblem({ ...SITELINK, link_text: "Free Next-Day Delivery Over £50" })).toBe(
      "Link Text is 31 of 25 characters."
    )
    expect(fieldProblem({ ...SITELINK, description2: null })).toBe(
      "Add both description lines, or neither."
    )
    // The server refuses these, so the card doesn't send them to be checked.
    const checked = args()
    const { entries } = editNewAsset(checked, [], SITELINK_KEY, "link_text", "")
    expect(canCheckAssets({ ...checked, entries })).toBe(false)
  })

  it("doesn't approve a link Google gave no answer for", () => {
    const value = raw()
    value._checks[`${C}/campaigns/20`].rows.pop()
    const unanswered = args(value)
    expect(needsCheck(unanswered, unanswered)).toBe(true)
    expect(
      linkRows(unanswered, unanswered).map((row) => [row.targetName, row.problem !== null])
    ).toEqual([
      ["Trail", false],
      ["Trail", false],
      ["Road", true],
    ])
  })

  it("counts a campaign's sitelinks once its changes apply", () => {
    const checked = args()
    const rows = linkRows(checked, checked)
    const of = (name: string) => rows.filter((row) => row.targetName === name)
    // Trail has 2, gains 1 and loses 1; Road already has the new one among its 5.
    expect(sitelinksAfter(2, of("Trail"))).toBe(2)
    expect(sitelinksAfter(5, of("Road"))).toBe(5)
  })

  it("gives a campaign added on the card the new assets once, up to the limit per target", () => {
    const checked = args()
    const entries = addTarget(checked, "campaign", campaign("30", "Kids"))
    expect(entries.at(-1)?.add.map((item) => item.key)).toEqual([SITELINK_KEY])
    expect(addTarget({ ...checked, entries }, "campaign", campaign("30", "Kids"))).toHaveLength(3)

    const callouts = (prefix: string) =>
      Array.from({ length: 15 }, (_, at) => ({ type: "callout", text: `${prefix} ${String(at)}` }))
    const many = args({
      entries: [
        { kind: "campaign", campaign: campaign("10", "Trail"), add: callouts("A") },
        { kind: "campaign", campaign: campaign("20", "Road"), add: callouts("B") },
      ],
    })
    const added = addTarget(many, "campaign", campaign("30", "Kids"))
    expect(added.at(-1)?.add).toHaveLength(20)
    expect(canCheckAssets({ ...many, entries: added })).toBe(true)
  })

  it("puts cancelled links back with Undo, after their campaign left the request too", () => {
    const checked = args()
    const rows = linkRows(checked, checked)
    const [removal, addition] = rows.filter((row) => row.targetName === "Trail")
    if (!removal || !addition) throw new Error("expected Trail's two links")
    const first = cancelLinks(checked, rows, new Set([removal.id]))
    expect(first.entries[0]?.remove).toEqual([])

    const second = cancelLinks({ ...checked, entries: first.entries }, rows, new Set([addition.id]))
    expect(second.entries.map((entry) => entry.label)).toEqual(["Road"])
    const undone = { ...removal, cancelled: true }
    const cancelled = [undone, { ...addition, cancelled: true }]
    const one = restoreRow(ASSET_CANCEL_CARD, second.entries, second.departed, undone)
    expect(one.at(-1)).toMatchObject({ label: "Trail", add: [] })
    expect(one.at(-1)?.remove.map((ref) => ref.assetId)).toEqual(["70"])

    const both = restoreParent(
      ASSET_CANCEL_CARD,
      second.entries,
      second.departed,
      cancelled,
      removal.targetKey
    )
    expect(both.at(-1)?.add.map((item) => item.key)).toEqual([SITELINK_KEY])
    expect(both.at(-1)?.remove.map((ref) => ref.assetId)).toEqual(["70"])
  })
})

describe("presenter", () => {
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
      googleAdsUpdateAssetsPresenter.render(
        props(
          {
            id: "assets-1",
            kind: "approval",
            name: "google_ads_update_assets",
            status: "awaiting_approval",
            args: raw(),
          },
          true
        )
      )
    )
    expect(approval).toContain("Add 1 sitelink in 2 campaigns in Northwind.")

    const priced = {
      ...raw(),
      entries: [
        raw().entries[0],
        { kind: "campaign", campaign: campaign("20", "Road"), add: [PRICE] },
      ],
    }
    const prices = html(
      googleAdsUpdateAssetsPresenter.render(
        props(
          {
            id: "assets-3",
            kind: "approval",
            name: "google_ads_update_assets",
            status: "awaiting_approval",
            args: priced,
          },
          true
        )
      )
    )
    expect(prices).toContain("Tier 2")

    const result = html(
      googleAdsUpdateAssetsPresenter.render(
        props({
          id: "assets-2",
          kind: "result",
          name: "google_ads_update_assets",
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
                  counts: {},
                  outcomes: [
                    {
                      target_kind: "campaign",
                      target_name: "Trail",
                      action: "add",
                      asset_type: "SITELINK",
                      asset_label: "Size Guide",
                      outcome: "added",
                    },
                  ],
                },
              },
            ],
          },
        })
      )
    )
    expect(result).toContain("Size Guide")
  })
})
