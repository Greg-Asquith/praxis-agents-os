// apps/web/tests/integrations/google-ads/optimise-search-terms.test.ts

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import {
  parseSearchTermsArgs,
  restoreDecision,
  searchedTarget,
  searchTermRows,
  searchTermsBlock,
  setDecisionAction,
  setDecisionTarget,
  targetOptions,
  type OptimiseSearchTermsArgs,
} from "@/integrations/google_ads/lib/search-terms"
import { googleAdsOptimiseSearchTermsPresenter } from "@/integrations/google_ads/presenters/optimise-search-terms"

const CUSTOMER = "1234567890"
const C = `customers/${CUSTOMER}`
const TRAIL = {
  customer_id: CUSTOMER,
  campaign_id: "10",
  ad_group_id: "40",
  label: "Trail Shoes",
  scope_label: "Trail",
}
const BRANDS = { customer_id: CUSTOMER, shared_set_id: "50", label: "Competitor Brands" }

function check(cost: string, problem: string | null = null) {
  return {
    unavailable: false,
    campaign_name: "Trail",
    ad_group_name: "Trail Shoes",
    target_name: "Trail",
    clicks: 12,
    cost,
    conversions: 0,
    state: "change",
    problem,
  }
}

function raw() {
  return {
    start_date: "2026-11-03",
    end_date: "2026-11-09",
    decisions: [
      {
        search_term: "running shoe jobs",
        ad_group: TRAIL,
        action: "add_negative",
        match_type: "BROAD",
        level: "campaign",
      },
      {
        search_term: "salomon speedcross",
        ad_group: TRAIL,
        action: "add_negative",
        match_type: "PHRASE",
        level: "list",
        negative_list: BRANDS,
      },
      { search_term: "fell shoes", ad_group: TRAIL, action: "add_keyword", match_type: "EXACT" },
    ],
    _accounts: [
      { customer_id: CUSTOMER, name: "Northwind", currency: "GBP", time_zone: "Europe/London" },
    ],
    _checks: {
      [`${C}/adGroups/40/add_negative/running shoe jobs`]: check("9.4"),
      [`${C}/adGroups/40/add_negative/salomon speedcross`]: check(
        "3.1",
        "Blocks “salomon trail”, a keyword you bid on in Trail Shoes."
      ),
      [`${C}/adGroups/40/add_keyword/fell shoes`]: check("31.2"),
    },
  }
}

function parsed(value: unknown = raw()): OptimiseSearchTermsArgs {
  const args = parseSearchTermsArgs(value)
  if (args === null) throw new Error("Expected valid args")
  return args
}

function edited(decisions: Record<string, unknown>[]) {
  return parsed({ ...raw(), decisions })
}

describe("search term decisions", () => {
  it("blocks approval on a problem, and on an edit until Google checks it, keeping its figures", () => {
    const args = parsed()
    expect(searchTermsBlock(args, args)).toBe("Fix or cancel 1 change to continue.")

    const keyword = `${C}/adGroups/40/add_keyword/fell shoes`
    const next = edited(setDecisionAction(args, new Set([keyword]), "add_negative").decisions)

    expect(searchTermsBlock(next, args)).toBe(
      "Click Check Changes so Google can check your edits, then approve."
    )
    const row = searchTermRows(next, args).find((item) => item.term === "fell shoes")
    expect(row).toMatchObject({ action: "add_negative", cost: 31.2, state: "unchecked" })
  })

  it("moves a negative to a list found by search, only in the term's own account", () => {
    const args = parsed()
    const jobs = new Set([`${C}/adGroups/40/add_negative/running shoe jobs`])
    const found = { customer_id: CUSTOMER, shared_set_id: "60", label: "Jobs and Careers" }

    const list = searchedTarget("list", found, "Jobs and Careers", CUSTOMER)
    if (!list) throw new Error("Expected the list as a target")
    expect(setDecisionTarget(args, jobs, list).decisions[0]).toMatchObject({
      level: "list",
      negative_list: found,
    })
    expect(
      searchedTarget("list", { ...found, customer_id: "9999999999" }, "Other", CUSTOMER)
    ).toBeNull()
  })

  it("drops a second decision that adds the same negative to the same list", () => {
    const args = parsed()
    const jobs = searchTermRows(args, args).find((row) => row.term === "running shoe jobs")
    if (!jobs) throw new Error("Expected the negative row")
    const brands = targetOptions(args, jobs).find((option) => option.value === "list:50")
    if (!brands) throw new Error("Expected the request's list as a quick choice")

    // Two decisions can't add the same negative to the same list.
    const salomon = `${C}/adGroups/40/add_negative/salomon speedcross`
    const clash = edited([
      ...args.decisions.map((decision) => decision.value),
      { ...args.decisions[1]?.value, ad_group: { ...TRAIL, ad_group_id: "41" } },
    ])
    const edit = setDecisionTarget(clash, new Set([salomon]), brands)
    expect(edit.decisions).toHaveLength(3)
    expect(edit.dropped).toHaveLength(1)
    expect(restoreDecision(edited(edit.decisions), edit.dropped[0] ?? {}).dropped).toEqual(
      edit.dropped
    )
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
      googleAdsOptimiseSearchTermsPresenter.render(
        props(
          {
            id: "search-terms-1",
            kind: "approval",
            name: "google_ads_optimise_search_terms",
            status: "awaiting_approval",
            args: raw(),
          },
          true
        )
      )
    )
    expect(approval).toContain("Act on 3 search terms from 3 Nov 2026 to 9 Nov 2026 in Northwind.")

    const result = html(
      googleAdsOptimiseSearchTermsPresenter.render(
        props({
          id: "search-terms-2",
          kind: "result",
          name: "google_ads_optimise_search_terms",
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
                  counts: {},
                  outcomes: [
                    {
                      search_term: "running shoe jobs",
                      action: "add_negative",
                      match_type: "BROAD",
                      target_kind: "campaign",
                      target_name: "Trail",
                      campaign_name: "Trail",
                      ad_group_name: "Trail Shoes",
                      cost: "9.4",
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
    expect(result).toContain("running shoe jobs")
  })
})
