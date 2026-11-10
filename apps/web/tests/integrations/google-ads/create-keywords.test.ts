// apps/web/tests/integrations/google-ads/create-keywords.test.ts

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import {
  createKeywordsApproveLabel,
  createKeywordsBlock,
  keywordAdGroupRows,
  parseCreateKeywordsArgs,
  serializeEntries,
  type CreateKeywordsArgs,
} from "@/integrations/google_ads/lib/create-keywords"
import { googleAdsCreateKeywordsPresenter } from "@/integrations/google_ads/presenters/create-keywords"

const CUSTOMER = "1234567890"
const group = (id: string) => `customers/${CUSTOMER}/adGroups/${id}`
const EXISTS = "“mens trail shoes” is already an exact match keyword in Men's Trail."

function adGroup(id: string, label: string) {
  return {
    entity_kind: "google_ads_ad_group",
    customer_id: CUSTOMER,
    campaign_id: "10",
    ad_group_id: id,
    label,
    scope_label: "Trail",
  }
}

function raw(over: Record<string, unknown> = {}) {
  return {
    status: "PAUSED",
    entries: [
      {
        ad_group: adGroup("20", "Men's Trail"),
        keywords: [
          { text: "mens trail shoes", match_type: "EXACT" },
          { text: "trail shoes for men", match_type: "PHRASE", cpc_bid: "0.9" },
        ],
      },
      {
        ad_group: adGroup("21", "Waterproof"),
        keywords: [{ text: "waterproof trail shoes", match_type: "BROAD" }],
      },
    ],
    _accounts: [
      { customer_id: CUSTOMER, name: "Northwind", currency: "GBP", time_zone: "Europe/London" },
    ],
    _ad_groups: {
      [group("20")]: {
        name: "Men's Trail",
        campaign_name: "Trail",
        strategy_name: "Manual CPC",
        uses_cpc_bid: true,
        default_bid: "0.85",
        problem: null,
      },
      [group("21")]: {
        name: "Waterproof",
        campaign_name: "Trail",
        strategy_name: "Maximise Conversions",
        uses_cpc_bid: false,
        default_bid: null,
        problem: null,
      },
    },
    _checks: {
      [`${group("20")}/EXACT/mens trail shoes`]: { unavailable: false, problem: EXISTS },
      [`${group("20")}/PHRASE/trail shoes for men`]: { unavailable: false, problem: null },
      [`${group("21")}/BROAD/waterproof trail shoes`]: { unavailable: false, problem: null },
    },
    ...over,
  }
}

function parsed(value: unknown = raw()): CreateKeywordsArgs {
  const args = parseCreateKeywordsArgs(value)
  if (args === null) throw new Error("Expected valid args")
  return args
}

describe("approval", () => {
  it("holds each ad group's problems to Google's check, and an edit to a new check", () => {
    const checked = parsed()
    const rows = keywordAdGroupRows(checked, checked)
    expect(rows.map((row) => [row.name, row.bid, row.problems])).toEqual([
      ["Men's Trail", "£0.85", 1],
      ["Waterproof", "Maximise Conversions", 0],
    ])
    expect(createKeywordsBlock(checked, checked)).toBe("Fix or cancel 1 keyword to continue.")
    expect(createKeywordsApproveLabel(checked)).toBe("Add 2 Keywords")

    // Cancelling the duplicate leaves a request Google hasn't seen, so it waits for a check.
    const [men, waterproof] = checked.entries
    if (!men || !waterproof) throw new Error("Expected two ad groups")
    const edited = {
      ...checked,
      entries: [{ ...men, keywords: men.keywords.slice(1) }, waterproof],
    }
    expect(createKeywordsBlock(edited, checked)).toBe(
      "Click Check Changes so Google can check your edits, then approve."
    )
  })

  it("sends each ad group's own keywords with the agent's reference unchanged", () => {
    const args = parsed()
    const sent = serializeEntries(args.entries)
    expect(sent[0]?.["ad_group"]).toEqual(adGroup("20", "Men's Trail"))
    expect(sent.map((entry) => entry["keywords"])).toEqual([
      [
        { text: "mens trail shoes", match_type: "EXACT", cpc_bid: null, final_url: null },
        { text: "trail shoes for men", match_type: "PHRASE", cpc_bid: "0.9", final_url: null },
      ],
      [{ text: "waterproof trail shoes", match_type: "BROAD", cpc_bid: null, final_url: null }],
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

  it("renders the ad groups above the open one's keywords, and the result", () => {
    const approval = html(
      googleAdsCreateKeywordsPresenter.render(
        props(
          {
            id: "keywords-1",
            kind: "approval",
            name: "google_ads_create_keywords",
            status: "awaiting_approval",
            args: raw(),
          },
          true
        )
      )
    )
    // The ad groups come first; below them, only the open ad group's keywords.
    const table = approval.indexOf('aria-label="Ad Groups"')
    expect(table).toBeGreaterThan(-1)
    expect(table).toBeLessThan(approval.indexOf("mens trail shoes"))
    expect(approval).not.toContain("waterproof trail shoes")

    const result = html(
      googleAdsCreateKeywordsPresenter.render(
        props({
          id: "keywords-2",
          kind: "result",
          name: "google_ads_create_keywords",
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
                  status: "PAUSED",
                  counts: { added: 1, already_set: 0, failed: 0, unverified: 0 },
                  keywords: [
                    {
                      text: "trail shoes for men",
                      match_type: "PHRASE",
                      cpc_bid: "0.9",
                      final_url: null,
                      ad_group: group("20"),
                      ad_group_name: "Men's Trail",
                      campaign_name: "Trail",
                      resource_name: `customers/${CUSTOMER}/adGroupCriteria/20~91`,
                      outcome: "added",
                    },
                  ],
                  keywords_truncated: false,
                },
              },
            ],
          },
        })
      )
    )
    expect(result).toContain("1 added · added paused")
  })
})
