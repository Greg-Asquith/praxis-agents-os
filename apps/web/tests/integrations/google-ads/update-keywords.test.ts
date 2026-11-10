// apps/web/tests/integrations/google-ads/update-keywords.test.ts

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import {
  addableSettings,
  editedKeywordChanges,
  keywordRows,
  keywordsApproveLabel,
  keywordsBlock,
  parseUpdateKeywordsArgs,
  parseUrls,
  replacesKeyword,
  restoredKeywordChanges,
  type UpdateKeywordsArgs,
} from "@/integrations/google_ads/lib/update-keywords"
import { googleAdsUpdateKeywordsPresenter } from "@/integrations/google_ads/presenters/update-keywords"

const CUSTOMER = "1234567890"
const key = (id: string) => `customers/${CUSTOMER}/adGroupCriteria/20~${id}`
const EXISTS = "“trail shoes” is already a phrase match keyword in Trail Shoes."

function keyword(id: string) {
  return {
    customer_id: CUSTOMER,
    campaign_id: "10",
    ad_group_id: "20",
    criterion_id: id,
    text: "trail shoes",
    match_type: "BROAD",
    status: "ENABLED",
    label: "trail shoes",
  }
}

function check(over: Record<string, unknown> = {}) {
  return {
    unavailable: false,
    text: "trail shoes",
    match_type: "BROAD",
    ad_group_name: "Trail Shoes",
    campaign_name: "Trail",
    strategy_name: "Manual CPC",
    bids_used: ["cpc_bid"],
    current: { match_type: "BROAD", cpc_bid: "0.64", final_urls: [] },
    requested: { match_type: "PHRASE", cpc_bid: "0.74" },
    problem: null,
    problems: { match_type: EXISTS },
    ...over,
  }
}

function raw(over: Record<string, unknown> = {}) {
  return {
    changes: [{ keyword: keyword("40"), match_type: "PHRASE", cpc_bid: "0.74" }],
    _accounts: [
      { customer_id: CUSTOMER, name: "Northwind", currency: "GBP", time_zone: "Europe/London" },
    ],
    _checks: { [key("40")]: check() },
    ...over,
  }
}

function parsed(value: unknown = raw()): UpdateKeywordsArgs {
  const args = parseUpdateKeywordsArgs(value)
  if (args === null) throw new Error("Expected valid args")
  return args
}

describe("approval", () => {
  it("marks a new match type as a replacement and holds its problem to the value Google checked", () => {
    const checked = parsed()
    const [match, bid] = keywordRows(checked, checked)
    expect(match && replacesKeyword(match)).toBe(true)
    expect([match?.problem, bid?.problem]).toEqual([EXISTS, null])
    expect(keywordsBlock(checked, checked)).toBe("Fix or cancel 1 change to continue.")

    // Back to the live match type, the row is already set and waits for a new check.
    const next = parsed({
      ...raw(),
      changes: editedKeywordChanges(checked, new Set([`${key("40")}|match_type`]), () => "BROAD"),
    })
    const [edited] = keywordRows(next, checked)
    expect(edited && replacesKeyword(edited)).toBe(false)
    expect(edited?.problem).toBeNull()
    expect(keywordsBlock(next, checked)).toBe(
      "Click Check Changes so Google can check your edits, then approve."
    )
  })

  it("writes a cleared bid as none, URL lists as lists, and URL options inside url_options", () => {
    const args = parsed(
      raw({
        changes: [{ keyword: keyword("40"), cpc_bid: "0.74", final_urls: ["https://example.com"] }],
      })
    )
    const ids = new Set([`${key("40")}|cpc_bid`, `${key("40")}|final_urls`])

    expect(
      editedKeywordChanges(args, ids, ({ setting }) => (setting === "cpc_bid" ? null : []))
    ).toEqual([{ keyword: keyword("40"), cpc_bid: "none", final_urls: [] }])
    expect(
      restoredKeywordChanges(parsed(raw({ changes: [] })), [
        { key: key("40"), keyword: keyword("40"), setting: "tracking_template", value: null },
      ])
    ).toEqual([{ keyword: keyword("40"), url_options: { tracking_template: "" } }])
    expect(parseUrls("https://example.com/a  https://example.com/b")).toEqual([
      "https://example.com/a",
      "https://example.com/b",
    ])
    expect(parseUrls("example.com")).toBeNull()
  })

  it("offers a max CPC only where the campaign's strategy uses keyword bids", () => {
    const smart = parsed(
      raw({
        changes: [{ keyword: keyword("40"), match_type: "PHRASE" }],
        _checks: { [key("40")]: check({ bids_used: ["target_cpa"] }) },
      })
    )
    const settings = addableSettings(smart, keywordRows(smart, smart), key("40")).map(
      (item) => item.setting
    )
    expect(settings).not.toContain("cpc_bid")
    expect(settings).toContain("final_urls")
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
    const sole = raw({
      changes: [{ keyword: keyword("40"), match_type: "PHRASE" }],
      _checks: { [key("40")]: check({ requested: { match_type: "PHRASE" }, problems: {} }) },
    })
    expect(keywordsApproveLabel(parsed(sole))).toBe("Change Match Type")
    const approval = html(
      googleAdsUpdateKeywordsPresenter.render(
        props(
          {
            id: "keywords-1",
            kind: "approval",
            name: "google_ads_update_keywords",
            status: "awaiting_approval",
            args: sole,
          },
          true
        )
      )
    )
    expect(approval).toContain("Pauses the broad keyword and adds a phrase one.")

    const result = html(
      googleAdsUpdateKeywordsPresenter.render(
        props({
          id: "keywords-2",
          kind: "result",
          name: "google_ads_update_keywords",
          status: "completed",
          args: sole,
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
                  counts: { updated: 1, already_set: 0, failed: 0, unverified: 0 },
                  keywords: [
                    {
                      resource_name: key("40"),
                      text: "trail shoes",
                      match_type: "BROAD",
                      ad_group_name: "Trail Shoes",
                      campaign_name: "Trail",
                      replacement: key("91"),
                      read_back: true,
                      outcome: "updated",
                      settings: [
                        {
                          setting: "match_type",
                          before: "BROAD",
                          requested: "PHRASE",
                          after: "PHRASE",
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
    expect(result).toContain("Old keyword paused, new keyword added")
  })
})
