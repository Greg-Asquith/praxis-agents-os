// apps/web/tests/integrations/google-ads/update-budgets.test.ts

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import {
  budgetCounts,
  budgetRows,
  budgetsBlock,
  budgetsNeedCheck,
  editedBudgetChanges,
  monthAtAmount,
  parseUpdateBudgetsArgs,
  totalDailyDelta,
  withAmount,
  withNetworkCap,
  withNetworkPriority,
  type UpdateBudgetsArgs,
} from "@/integrations/google_ads/lib/update-budgets"
import { googleAdsUpdateBudgetsPresenter } from "@/integrations/google_ads/presenters/update-budgets"

const CUSTOMER = "1234567890"
const campaignKey = (id: string) => `customers/${CUSTOMER}/campaigns/${id}`
const budgetKey = (id: string) => `customers/${CUSTOMER}/campaignBudgets/${id}`
const TOO_LOW = "Google says: The budget is below the minimum."

function campaign(id: string) {
  return { customer_id: CUSTOMER, campaign_id: id, label: `Campaign ${id}` }
}

function view(id: string, over: Record<string, unknown> = {}) {
  return {
    resource_name: budgetKey(id),
    name: `Budget ${id}`,
    shared: false,
    amount: "45",
    delivery: "STANDARD",
    campaign_count: 1,
    campaigns: [{ name: "Trail Running Shoes", spend: "300" }],
    spend_this_month: "300",
    ...over,
  }
}

function check(over: Record<string, unknown> = {}) {
  return {
    unavailable: false,
    kind: "campaign",
    name: "Trail Running Shoes",
    budget: view("1"),
    destination: null,
    removes_budget: false,
    spend_this_month: "300",
    days_left: 10,
    current: { amount: "45", delivery: "STANDARD", shared_budget: budgetKey("1") },
    requested: { amount: "0.5" },
    problem: TOO_LOW,
    ...over,
  }
}

function raw(over: Record<string, unknown> = {}) {
  return {
    changes: [{ campaign: campaign("10"), amount: "0.50" }],
    _accounts: [
      { customer_id: CUSTOMER, name: "Northwind", currency: "GBP", time_zone: "Europe/London" },
    ],
    _checks: { [campaignKey("10")]: check() },
    ...over,
  }
}

function parsed(value: unknown = raw()): UpdateBudgetsArgs {
  const args = parseUpdateBudgetsArgs(value)
  if (args === null) throw new Error("Expected valid args")
  return args
}

describe("approval", () => {
  it("holds Google's answer to the amount it checked, and an edit waits for a new check", () => {
    const checked = parsed()
    expect(budgetRows(checked, checked)[0]?.problem).toBe(TOO_LOW)
    expect(budgetsBlock(checked, checked)).toBe("Fix or cancel 1 change to continue.")

    const next = parsed({
      ...raw(),
      changes: editedBudgetChanges(checked, new Set([campaignKey("10")]), (change) =>
        withAmount(change, "60.00")
      ),
    })

    expect(budgetRows(next, checked)[0]?.problem).toBeNull()
    expect(budgetsBlock(next, checked)).toBe(
      "Click Check Changes so Google can check your edits, then approve."
    )
  })

  it("adds the new amount for each day left to this month's spend", () => {
    const args = parsed(
      raw({
        changes: [{ campaign: campaign("10"), amount: "60" }],
        _checks: { [campaignKey("10")]: check({ requested: { amount: "60" }, problem: null }) },
      })
    )
    const [row] = budgetRows(args, args)
    if (!row) throw new Error("Expected a row")

    expect(monthAtAmount(row, row.amount)).toBe(900)
    expect(totalDailyDelta([row])).toBe(15)
  })
})

describe("edits", () => {
  it("matches a network order to the code Google's check answered for, in any order given", () => {
    // The server lists a tier's networks alphabetically; the request doesn't have to.
    const code = "OWNED_AND_OPERATED>GOOGLE_DISPLAY+SEARCH_PARTNER:20"
    const priority = {
      first: ["OWNED_AND_OPERATED"],
      then: [{ network: "SEARCH_PARTNER", cap_percent: 20 }, { network: "GOOGLE_DISPLAY" }],
    }
    const checked = parsed(
      raw({
        changes: [{ campaign: campaign("10"), network_priority: priority }],
        _checks: {
          [campaignKey("10")]: check({
            current: { network_priority: "ACCOUNT_DEFAULT" },
            requested: { network_priority: code },
          }),
        },
      })
    )
    const [row] = budgetRows(checked, checked)
    if (!row?.change || !row.networkPriority || row.networkPriority === "account_default")
      throw new Error("Expected a network order")
    expect(row.problem).toBe(TOO_LOW)

    const capped = withNetworkCap(row.networkPriority, "GOOGLE_DISPLAY", 5)
    const next = parsed({
      ...raw(),
      changes: [withNetworkPriority(row.change, capped)],
    })

    expect(next.changes[0]?.entry["network_priority"]).toEqual({
      first: ["OWNED_AND_OPERATED"],
      then: [
        { network: "SEARCH_PARTNER", cap_percent: 20 },
        { network: "GOOGLE_DISPLAY", cap_percent: 5 },
      ],
    })
    expect(budgetRows(next, checked)[0]?.problem).toBeNull()
    expect(budgetsNeedCheck(next, checked)).toBe(true)
  })

  it("leaves a move onto a shared budget without an amount, which Google Ads refuses", () => {
    const move = {
      campaign: campaign("10"),
      use_shared_budget: { customer_id: CUSTOMER, budget_id: "2" },
    }
    const args = parsed(raw({ changes: [move, { campaign: campaign("11"), amount: "45" }] }))

    expect(
      editedBudgetChanges(args, new Set([campaignKey("10"), campaignKey("11")]), (change) =>
        withAmount(change, "60")
      )
    ).toEqual([move, { campaign: campaign("11"), amount: "60" }])
  })

  it("counts a campaign once when its shared budget is in the request too", () => {
    const shared = view("2", { shared: true })
    const args = parsed(
      raw({
        changes: [
          { campaign: campaign("10"), amount: "60" },
          { budget: { customer_id: CUSTOMER, budget_id: "2", label: "Budget 2" }, amount: "80" },
        ],
        _checks: {
          [campaignKey("10")]: check({ budget: shared }),
          [budgetKey("2")]: check({ kind: "budget", name: "Budget 2", budget: shared }),
        },
      })
    )

    expect(budgetCounts(budgetRows(args, args)).campaigns).toBe(1)
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
      googleAdsUpdateBudgetsPresenter.render(
        props(
          {
            id: "budgets-1",
            kind: "approval",
            name: "google_ads_update_budgets",
            status: "awaiting_approval",
            // A network order beside the amount, so its line renders too.
            args: raw({
              changes: [
                {
                  campaign: campaign("10"),
                  amount: "0.50",
                  network_priority: { first: ["OWNED_AND_OPERATED"] },
                },
              ],
              _checks: {
                [campaignKey("10")]: check({
                  requested: { amount: "0.5", network_priority: "OWNED_AND_OPERATED" },
                }),
              },
            }),
          },
          true
        )
      )
    )
    expect(approval).toContain(TOO_LOW)

    const result = html(
      googleAdsUpdateBudgetsPresenter.render(
        props({
          id: "budgets-2",
          kind: "result",
          name: "google_ads_update_budgets",
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
                  budgets: [
                    {
                      resource_name: campaignKey("30"),
                      kind: "campaign",
                      name: "Walking Socks",
                      budget_name: "Walking Socks budget",
                      shared: false,
                      spend_this_month: "12",
                      read_back: true,
                      settings: [
                        {
                          setting: "shared_budget",
                          before: "Walking Socks budget",
                          requested: "Footwear Shared",
                          after: "Footwear Shared",
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
    expect(result).toContain("Footwear Shared")
  })
})
