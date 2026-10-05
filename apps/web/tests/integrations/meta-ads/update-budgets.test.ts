import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import { budgetNotes, parseBudgetChangeArgs } from "@/integrations/meta_ads/lib/budget-change"
import { metaAdsUpdateBudgetsPresenter } from "@/integrations/meta_ads/presenters/update-budgets"

const adSet = {
  version: 1,
  entity_kind: "meta_ads_ad_set",
  label: "Prospecting",
  account_id: "111",
  campaign_id: "1",
  adset_id: "8",
  status: "ACTIVE",
  budget: { kind: "daily", amount: "15", remaining: null },
  currency: "EUR",
}
const campaign = {
  version: 1,
  entity_kind: "meta_ads_campaign",
  label: "Spring",
  account_id: "111",
  campaign_id: "9",
  budget: { kind: "lifetime", amount: "1000", remaining: "600" },
  currency: "EUR",
}
const APPROVE_DISABLED = /<button[^>]*\sdisabled=""[^>]*>Approve/

describe("Meta Ads budget notes", () => {
  it("estimates a month of a daily budget and shows what a lifetime budget has spent", () => {
    const args = parseBudgetChangeArgs({
      updates: [
        { ad_set: adSet, amount: "10" },
        { campaign, amount: "1200" },
      ],
      _budget_checks: { "8": { recent_changes: 2 }, "9": { spent: "400" } },
    })
    const [daily, lifetime] = args?.changes.map(budgetNotes) ?? []

    expect(daily?.[0]).toContain("€304.00")
    expect(daily?.[1]).toContain("2 times in the last hour")
    expect(lifetime).toEqual([expect.stringContaining("€400.00")])
  })

  it("keeps the throttle warning when incomplete history found no changes", () => {
    const notes = (check: Record<string, unknown>) =>
      parseBudgetChangeArgs({
        updates: [{ campaign, amount: "1200" }],
        _budget_checks: { "9": check },
      })?.changes.map(budgetNotes)[0]

    expect(notes({ recent_changes: 0, recent_changes_complete: true })).toEqual([])
    expect(notes({ recent_changes: 0, recent_changes_complete: false })).toHaveLength(1)
  })

  it("rejects an update that names both or neither object", () => {
    expect(parseBudgetChangeArgs({ updates: [{ amount: "10" }] })).toBeNull()
    expect(
      parseBudgetChangeArgs({ updates: [{ ad_set: adSet, campaign, amount: "10" }] })
    ).toBeNull()
  })
})

describe("Meta Ads update budgets presenter", () => {
  it("blocks approval only when a server check found a problem", () => {
    const args = { updates: [{ ad_set: adSet, amount: "25" }] }
    expect(render(approval({ ...args, _budget_checks: { "8": {} } }))).not.toMatch(APPROVE_DISABLED)

    const blocked = render(
      approval({ ...args, _budget_checks: { "8": { problem: "Change the campaign instead." } } })
    )
    expect(blocked).toMatch(APPROVE_DISABLED)
    expect(blocked).toContain("Change the campaign instead.")
  })

  it("keeps the amount Meta shows on an unconfirmed row", () => {
    const html = render(
      settled({
        provider_key: "meta_ads",
        external_id: "111",
        display_name: "Example ad account",
        status: "error",
        error_code: "unverified_mutation",
        error_message: null,
        data: {
          account_id: "111",
          currency: "EUR",
          budgets: [
            {
              object_type: "adset",
              object_id: "8",
              object_name: "Prospecting",
              budget_kind: "daily",
              previous_amount: "10",
              requested_amount: "25",
              amount: "15",
              outcome: "unverified",
              error_code: "BUDGET_NOT_CONFIRMED",
              message:
                "Meta Ads accepted the change, but the budget still shows a different amount.",
            },
          ],
        },
      })
    )
    expect(html).toContain("Prospecting")
    expect(html).toContain("verify whether Meta Ads updated")
    // Only the read-back amount is 15; before and requested differ from it.
    expect(html).toContain("€15.00")
  })
})

function approval(args: Record<string, unknown>) {
  return metaAdsUpdateBudgetsPresenter.render(
    props(
      {
        id: "a1",
        kind: "approval",
        name: "meta_ads_update_budgets",
        status: "awaiting_approval",
        args,
      },
      true
    )
  )
}

function settled(entry: unknown) {
  return metaAdsUpdateBudgetsPresenter.render(
    props({
      id: "r1",
      kind: "result",
      name: "meta_ads_update_budgets",
      status: "completed",
      args: { updates: [{ ad_set: adSet, amount: "25" }] },
      result: { results: [entry] },
    })
  )
}

function props(activity: ToolActivity, withApproval = false) {
  return {
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
    providerKey: "meta_ads",
  }
}

function render(node: ReactNode) {
  return renderToStaticMarkup(createElement("div", null, node))
}
