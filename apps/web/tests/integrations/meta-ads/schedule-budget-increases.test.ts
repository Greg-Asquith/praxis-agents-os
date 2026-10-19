// apps/web/tests/integrations/meta-ads/schedule-budget-increases.test.ts

import { describe, expect, it } from "vitest"

import {
  budgetScheduleProblem,
  editPeriods,
  highestBudget,
  parseBudgetScheduleArgs,
  periodProblems,
  periodRows,
} from "@/integrations/meta_ads/lib/budget-schedule"
import { metaAdsScheduleBudgetIncreasesPresenter } from "@/integrations/meta_ads/presenters/schedule-budget-increases"
import { APPROVE_DISABLED, props, render } from "./presenter-harness"

const campaign = {
  version: 1,
  entity_kind: "meta_ads_campaign",
  label: "Black Friday",
  account_id: "111",
  campaign_id: "9",
  currency: "GBP",
}
const blackFriday = { start: "2026-11-27T00:00", end: "2026-11-30T00:00", increase_percent: 50 }
const checks = {
  unavailable: false,
  currency: "GBP",
  time_zone: "Europe/London",
  now: "2026-11-01T12:00",
  daily_budget: "100",
  problems: [],
  existing_count: 1,
  existing: [
    {
      start: "2026-12-24T00:00",
      end: "2026-12-26T00:00",
      value_type: "ABSOLUTE",
      value: "5000",
      increase_amount: "50",
    },
  ],
  periods: [{ ...blackFriday, problem: null }],
}

function parse(periods: Record<string, unknown>[], extra: Record<string, unknown> = {}) {
  const args = parseBudgetScheduleArgs({
    campaign,
    periods,
    _schedule_checks: { ...checks, ...extra },
  })
  if (!args) throw new Error("expected budget schedule args")
  return args
}

describe("Meta Ads budget increase periods", () => {
  it("judges an edited period again instead of keeping the server's verdict", () => {
    const shown = parse([{ ...blackFriday, increase_percent: 900 }], {
      periods: [{ ...blackFriday, increase_percent: 900, problem: "Too high." }],
    })
    expect(periodProblems(shown)[0]).toBe("Too high.")

    const edited = parse(editPeriods(periodRows(shown, shown), 0, { increasePercent: "50" }))
    expect(periodProblems(edited)[0]).toBeNull()
    expect(highestBudget(edited)).toBe(150)
  })

  it("refuses an increase above 8 times the daily budget and overlaps", () => {
    const args = parse([
      { start: "2026-11-27T00:00", end: "2026-11-28T00:00", increase_amount: "700.01" },
      { start: "2026-12-25T00:00", end: "2026-12-25T06:00", increase_amount: "20" },
      { start: "2026-11-29T00:00", end: "2026-11-29T02:00", increase_amount: "20" },
    ])

    expect(periodProblems(args)[0]).toContain("£700.00")
    expect(periodProblems(args)[1]).toContain("overlaps")
    expect(periodProblems(args)[2]).toContain("3 hours")
    expect(budgetScheduleProblem(args)).not.toBeNull()
  })

  it("lines edited periods up with the proposal so a left-out one can come back", () => {
    const later = { start: "2026-12-01T00:00", end: "2026-12-02T00:00", increase_amount: "20" }
    const last = { start: "2026-12-05T00:00", end: "2026-12-06T00:00", increase_amount: "30" }
    const proposed = parse([blackFriday, later, last])
    // The first period edited and the second left out.
    const current = parse([{ ...blackFriday, increase_percent: 60 }, last])
    const rows = periodRows(proposed, current)
    expect(rows.map((row) => row.included)).toEqual([true, false, true])

    expect(editPeriods(rows, 1, { included: true })).toEqual([
      { ...blackFriday, increase_percent: 60 },
      later,
      last,
    ])
    const none = parse(editPeriods(periodRows(proposed, parse([])), 0, { included: false }))
    expect(budgetScheduleProblem(none)).not.toBeNull()
  })
})

describe("Meta Ads schedule budget increases presenter", () => {
  it("blocks approval for a target Meta won't schedule", () => {
    const args = { campaign, periods: [blackFriday] }
    expect(render(approval({ ...args, _schedule_checks: checks }))).not.toMatch(APPROVE_DISABLED)

    const blocked = render(
      approval({
        ...args,
        _schedule_checks: { ...checks, problems: ["This campaign has a lifetime budget."] },
      })
    )
    expect(blocked).toMatch(APPROVE_DISABLED)
  })
})

function approval(args: Record<string, unknown>) {
  return metaAdsScheduleBudgetIncreasesPresenter.render(
    props(
      {
        id: "a1",
        kind: "approval",
        name: "meta_ads_schedule_budget_increases",
        status: "awaiting_approval",
        args,
      },
      true
    )
  )
}
