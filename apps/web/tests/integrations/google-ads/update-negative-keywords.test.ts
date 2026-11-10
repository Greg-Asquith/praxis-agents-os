// apps/web/tests/integrations/google-ads/update-negative-keywords.test.ts

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import {
  addKeywords,
  cancelRows,
  negativeBlock,
  negativeRows,
  parseNegativeKeywordsArgs,
  restoreRow,
  serializeEntries,
  setMatchType,
  targetEntry,
  type UpdateNegativeKeywordsArgs,
} from "@/integrations/google_ads/lib/negative-keywords"
import { googleAdsUpdateNegativeKeywordsPresenter } from "@/integrations/google_ads/presenters/update-negative-keywords"

const CUSTOMER = "1234567890"
const C = `customers/${CUSTOMER}`

function campaign(id: string, label: string) {
  return { customer_id: CUSTOMER, campaign_id: id, label }
}

function raw(checks: Record<string, unknown> = {}) {
  return {
    entries: [
      {
        kind: "campaign",
        campaign: campaign("10", "Trail"),
        add: [
          { text: "jobs", match_type: "BROAD" },
          { text: "free", match_type: "PHRASE" },
        ],
      },
      {
        kind: "new_list",
        new_list: "Competitor Brands",
        add: [{ text: "salomon", match_type: "PHRASE" }],
        apply_to_campaigns: [campaign("20", "Road")],
      },
    ],
    _accounts: [
      { customer_id: CUSTOMER, name: "Northwind", currency: "GBP", time_zone: "Europe/London" },
    ],
    _checks: {
      [`${C}/campaigns/10`]: {
        unavailable: false,
        name: "Trail",
        problem: null,
        rows: [
          { item: "keyword", key: "BROAD:jobs", action: "add", state: "change", problem: null },
          {
            item: "keyword",
            key: "PHRASE:free",
            action: "add",
            state: "change",
            problem: "Blocks “free running shoes”, a keyword you bid on in Trail Shoes.",
          },
        ],
      },
      [`${C}/newSharedSets/competitor brands`]: {
        unavailable: false,
        name: "Competitor Brands",
        problem: null,
        rows: [
          { item: "keyword", key: "PHRASE:salomon", action: "add", state: "change", problem: null },
          {
            item: "campaign",
            key: `${C}/campaigns/20`,
            action: "add",
            state: "change",
            problem: null,
          },
        ],
      },
      ...checks,
    },
  }
}

function parsed(value: unknown = raw()): UpdateNegativeKeywordsArgs {
  const args = parseNegativeKeywordsArgs(value)
  if (args === null) throw new Error("Expected valid args")
  return args
}

describe("negative keyword changes", () => {
  it("drops a new list left without keywords, and Undo brings it back whole", () => {
    const args = parsed()
    const rows = negativeRows(args, args)
    const salomon = rows.find((row) => row.name === "salomon")
    if (!salomon) throw new Error("Expected the new list's keyword")

    const edit = cancelRows(args, rows, new Set([salomon.id]))

    expect(edit.entries.map((entry) => entry.kind)).toEqual(["campaign"])
    expect(edit.dropped.map((row) => row.name)).toEqual(["salomon", "Road"])
    const departed = args.entries.filter((entry) => entry.kind === "new_list")
    const restored = restoreRow({ ...args, entries: edit.entries }, departed, salomon)
    expect(serializeEntries(restored)).toEqual(serializeEntries(args.entries))
  })

  it("blocks approval on a problem, and on an edit until Google checks it", () => {
    const args = parsed()
    expect(negativeBlock(args, args)).toBe("Fix or cancel 1 change to continue.")

    const rows = negativeRows(args, args)
    const free = rows.find((row) => row.name === "free")
    if (!free) throw new Error("Expected the blocked keyword")
    const edited = {
      ...args,
      entries: setMatchType(args, rows, new Set([free.id]), "EXACT").entries,
    }
    expect(negativeBlock(edited, args)).toBe(
      "Click Check Changes so Google can check your edits, then approve."
    )
    expect(negativeRows(edited, args).find((row) => row.name === "free")?.problem).toBeNull()
  })

  it("adds keywords to a target found by search as a new entry, keeping the others", () => {
    const args = parsed()
    const found = targetEntry("ad_group", {
      customer_id: CUSTOMER,
      campaign_id: "10",
      ad_group_id: "40",
      label: "Trail Shoes",
    })
    const trail = args.entries[0]
    if (!found || !trail) throw new Error("Expected targets")

    const entries = addKeywords(args, [trail, found], [{ text: "jobs", matchType: "EXACT" }])

    expect(entries.slice(1, 2)).toEqual(args.entries.slice(1, 2))
    expect(serializeEntries(entries)[0]?.["add"]).toEqual([
      { match_type: "BROAD", text: "jobs" },
      { match_type: "PHRASE", text: "free" },
      { match_type: "EXACT", text: "jobs" },
    ])
    expect(serializeEntries(entries)[2]).toMatchObject({
      kind: "ad_group",
      ad_group: { ad_group_id: "40" },
      add: [{ match_type: "EXACT", text: "jobs" }],
    })
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
      googleAdsUpdateNegativeKeywordsPresenter.render(
        props(
          {
            id: "negatives-1",
            kind: "approval",
            name: "google_ads_update_negative_keywords",
            status: "awaiting_approval",
            args: raw(),
          },
          true
        )
      )
    )
    expect(approval).toContain("Block 3 searches in 1 campaign and a new list in Northwind.")

    const result = html(
      googleAdsUpdateNegativeKeywordsPresenter.render(
        props({
          id: "negatives-2",
          kind: "result",
          name: "google_ads_update_negative_keywords",
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
                      item: "keyword",
                      action: "add",
                      name: "jobs",
                      match_type: "BROAD",
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
    expect(result).toContain("jobs")
  })
})
