// apps/web/tests/integrations/google-ads/update-asset-groups.test.ts

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { restoreRow } from "@/integrations/ads/lib/cancelled-rows"
import {
  addGroupItem,
  assetGroupsBlock,
  cancelGroupChanges,
  editGroupChange,
  GROUP_CANCEL_CARD,
  groupChangeRows,
  kindSummary,
  parseUpdateAssetGroupsArgs,
  type UpdateAssetGroupsArgs,
} from "@/integrations/google_ads/lib/update-asset-groups"
import { googleAdsUpdateAssetGroupsPresenter } from "@/integrations/google_ads/presenters/update-asset-groups"

const CUSTOMER = "1234567890"
const GROUP = `customers/${CUSTOMER}/assetGroups/950`

function entry(over: Record<string, unknown> = {}) {
  return {
    asset_group: {
      customer_id: CUSTOMER,
      campaign_id: "10",
      asset_group_id: "950",
      label: "Rain Jackets",
    },
    add_assets: { headlines: ["Grip on  Every Trail"] },
    remove_assets: {
      headlines: ["Built for the Hills"],
      long_headlines: ["Waterproof jackets for every trail"],
    },
    ...over,
  }
}

const ROWS = [
  {
    row: "HEADLINE|Built for the Hills",
    action: "remove",
    item: "Built for the Hills",
    before: `customers/${CUSTOMER}/assetGroupAssets/950~503~HEADLINE`,
    state: "change",
    problem: null,
  },
  {
    row: "LONG_HEADLINE|Waterproof jackets for every trail",
    action: "remove",
    item: "Waterproof jackets for every trail",
    before: `customers/${CUSTOMER}/assetGroupAssets/950~510~LONG_HEADLINE`,
    state: "change",
    problem: "Every asset group needs at least 1 long headline; this would leave 0.",
  },
  {
    // The server keys text with its spaces collapsed.
    row: "HEADLINE|Grip on Every Trail",
    action: "add",
    item: "Grip on Every Trail",
    before: null,
    state: "change",
    problem: null,
  },
]

function args(entries: unknown[] = [entry()]) {
  return {
    entries,
    _accounts: [
      { customer_id: CUSTOMER, name: "Northwind", currency: "GBP", time_zone: "Europe/London" },
    ],
    _checks: {
      [GROUP]: {
        unavailable: false,
        name: "Rain Jackets",
        campaign_name: "PMax Hiking UK",
        problem: null,
        now: { HEADLINE: 3, LONG_HEADLINE: 1, DESCRIPTION: 2 },
        rows: ROWS,
      },
    },
  }
}

function parsed(value: unknown): UpdateAssetGroupsArgs {
  const result = parseUpdateAssetGroupsArgs(value)
  if (!result) throw new Error("expected update asset groups args")
  return result
}

describe("Google Ads update asset groups arguments", () => {
  it("matches each change to its check and blocks the removal under a minimum", () => {
    const value = parsed(args())
    const rows = groupChangeRows(value, value)

    expect(rows.map((row) => [row.row, row.state, row.problem !== null])).toEqual([
      ["HEADLINE|Built for the Hills", "change", false],
      ["LONG_HEADLINE|Waterproof jackets for every trail", "change", true],
      ["HEADLINE|Grip on Every Trail", "change", false],
    ])
    // A swap leaves the headline count where it was.
    const headlines = kindSummary(value, rows, GROUP)?.find((item) => item.kind === "HEADLINE")
    expect(headlines).toMatchObject({ now: 3, removing: 1, adding: 1, after: 3 })
    expect(assetGroupsBlock(value, value)).toBe(
      "Long Headlines would drop to 0; Google needs 1. Fix or cancel changes to continue."
    )
  })

  it("blocks approval as soon as a cancelled addition leaves a type under its minimum", () => {
    const value = parsed(args([entry({ remove_assets: { headlines: ["Built for the Hills"] } })]))
    const rows = groupChangeRows(value, value)
    const added = rows.find((row) => row.action === "add")
    if (!added) throw new Error("expected the added headline")

    const edit = cancelGroupChanges(value, rows, new Set([added.id]))

    expect(assetGroupsBlock({ ...value, entries: edit.entries }, value)).toBe(
      "Headlines would drop to 2; Google needs 3. Fix or cancel changes to continue."
    )
  })

  it("swaps an added audience for another and adds a theme only once", () => {
    const value = parsed(
      args([
        entry({
          add_audience_signals: [{ kind: "user_interest", key: "80276", name: "Software" }],
        }),
      ])
    )
    const audience = groupChangeRows(value, value).find((row) => row.kind === "audience_signal")
    if (!audience) throw new Error("expected the added audience")
    const swapped = editGroupChange(value, audience, {
      key: "80530",
      kind: "user_interest",
      name: "Enterprise Software",
    })
    expect(swapped[0]?.entry["add_audience_signals"]).toEqual([
      { key: "80530", kind: "user_interest", name: "Enterprise Software" },
    ])

    const once = addGroupItem(value, GROUP, "search_theme", "ai  software")
    const twice = addGroupItem({ ...value, entries: once }, GROUP, "search_theme", "ai software")
    expect(twice[0]?.entry["add_search_themes"]).toEqual(["ai  software"])
  })

  it("cancels a change out of its list, and Undo puts it back as it was", () => {
    const value = parsed(args())
    const rows = groupChangeRows(value, value)
    const longHeadline = rows.find((row) => row.kind === "LONG_HEADLINE")
    if (!longHeadline) throw new Error("expected the long headline removal")

    const edit = cancelGroupChanges(value, rows, new Set([longHeadline.id]))
    const remaining = edit.entries[0]?.entry["remove_assets"]
    expect(remaining).toEqual({ headlines: ["Built for the Hills"], long_headlines: [] })
    // What's left changes the counts Google checked, so it checks again before approval.
    expect(assetGroupsBlock({ ...value, entries: edit.entries }, value)).toMatch(/Check Changes/)

    const restored = restoreRow(GROUP_CANCEL_CARD, edit.entries, edit.departed, {
      ...longHeadline,
      cancelled: true,
    })
    expect(restored[0]?.entry).toEqual(entry())
  })

  it("edits custom parameters as text, and Undo restores a URL option that clears", () => {
    const options = {
      final_url_suffix: "",
      custom_parameters: [{ key: "season", value: "winter" }],
    }
    const value = parsed(args([entry({ url_options: options })]))
    const rows = groupChangeRows(value, value)
    const [suffix, parameters] = rows.filter((row) => row.action === "set")
    if (!suffix || !parameters) throw new Error("expected both URL options")
    // The server names each setting by its kind, and shows a cleared option as empty.
    expect([suffix.row, suffix.value, parameters.row, parameters.value]).toEqual([
      "final_url_suffix",
      "",
      "custom_parameters",
      "season=winter",
    ])

    const edited = editGroupChange(value, parameters, "season=summer, promo=x")
    expect(edited[0]?.entry["url_options"]).toEqual({
      final_url_suffix: "",
      custom_parameters: [
        { key: "season", value: "summer" },
        { key: "promo", value: "x" },
      ],
    })

    const edit = cancelGroupChanges(value, rows, new Set([suffix.id]))
    expect(edit.entries[0]?.entry["url_options"]).toEqual({
      custom_parameters: options.custom_parameters,
    })
    const restored = restoreRow(GROUP_CANCEL_CARD, edit.entries, edit.departed, {
      ...suffix,
      cancelled: true,
    })
    // An empty suffix still asks Google to clear the one that's live.
    expect(restored[0]?.entry["url_options"]).toMatchObject({ final_url_suffix: "" })
  })

  it("lets a group whose only change is cancelled leave the request, kept for Undo", () => {
    const only = entry({ add_assets: {}, remove_assets: { headlines: ["Built for the Hills"] } })
    const value = parsed(args([only]))
    const rows = groupChangeRows(value, value)

    const edit = cancelGroupChanges(value, rows, new Set(rows.map((row) => row.id)))

    expect(edit.entries).toEqual([])
    expect(edit.departed.map((group) => group.key)).toEqual([GROUP])
  })
})

describe("Google Ads update asset groups card", () => {
  it("renders the approval with the asset group first", () => {
    const html = renderToStaticMarkup(
      createElement(
        QueryClientProvider,
        { client: new QueryClient() },
        googleAdsUpdateAssetGroupsPresenter.render({
          activity: {
            id: "asset-group-edits-1",
            kind: "approval",
            name: "google_ads_update_asset_groups",
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
  })
})
