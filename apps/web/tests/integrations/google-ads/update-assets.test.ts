// apps/web/tests/integrations/google-ads/update-assets.test.ts

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import {
  addTarget,
  assetParents,
  assetsBlock,
  cancelLinks,
  editNewAsset,
  fieldProblem,
  linkRows,
  newAssetKey,
  newAssetRows,
  parseUpdateAssetsArgs,
  restoreLink,
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
  it("names a new asset as the server does, collapsing spaces", () => {
    expect(newAssetKey(SITELINK)).toBe(SITELINK_KEY)
  })

  it("shows a new asset once, and an edit changes it in every target and asks for a check", () => {
    const checked = args()
    const rows = linkRows(checked, checked)
    expect(newAssetRows(rows, checked)).toEqual([
      expect.objectContaining({ key: SITELINK_KEY, targets: 2 }),
    ])
    expect(assetsBlock(checked, checked)).toBeNull()

    const entries = editNewAsset(checked, SITELINK_KEY, "link_text", "Find Your Size")
    expect(entries.map((entry) => entry.add[0]?.value["link_text"])).toEqual([
      "Find Your Size",
      "Find Your Size",
    ])
    expect(assetsBlock({ ...checked, entries }, checked)).toMatch(/Check Changes/)
  })

  it("blocks a field over Google's limit and a sitelink with one description line", () => {
    expect(fieldProblem({ ...SITELINK, link_text: "Free Next-Day Delivery Over £50" })).toBe(
      "Link Text is 31 of 25 characters."
    )
    expect(fieldProblem({ ...SITELINK, description2: null })).toBe(
      "Add both description lines, or neither."
    )
  })

  it("warns when a campaign ends with fewer than four sitelinks", () => {
    const checked = args()
    const [trail, road] = assetParents(checked, linkRows(checked, checked), false)
    // Trail has 2, gains 1 and loses 1; Road already has the new one among its 5.
    expect(trail?.context).toContain("2 sitelinks after")
    expect(road?.context ?? "").not.toContain("after")
  })

  it("gives a campaign added on the card every new asset, once", () => {
    const checked = args()
    const entries = addTarget(checked, "campaign", campaign("30", "Kids"))
    expect(entries.at(-1)?.add.map((item) => item.key)).toEqual([SITELINK_KEY])
    expect(addTarget({ ...checked, entries }, "campaign", campaign("30", "Kids"))).toHaveLength(3)
  })

  it("puts a cancelled removal back with Undo", () => {
    const checked = args()
    const rows = linkRows(checked, checked)
    const removal = rows.find((row) => row.action === "remove")
    if (!removal) throw new Error("expected a removal")
    const edit = cancelLinks(checked, rows, new Set([removal.id]))
    expect(edit.entries[0]?.remove).toEqual([])

    const cancelled = { ...checked, entries: edit.entries }
    const restored = restoreLink(cancelled, edit.departed, { ...removal, cancelled: true })
    expect(restored[0]?.remove.map((ref) => ref.assetId)).toEqual(["70"])
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
