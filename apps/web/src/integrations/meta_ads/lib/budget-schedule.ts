// apps/web/src/integrations/meta_ads/lib/budget-schedule.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { budgetMoney, isBudgetAmount } from "@/integrations/meta_ads/lib/budget-change"
import { isNonEmptyString, isRecord } from "@/lib/guards"

type ScheduleObjectType = "campaign" | "adset"

export type BudgetPeriod = {
  start: string
  end: string
  // Exactly one of the two is set; each is as typed, so it can be invalid while edited.
  increaseAmount: string | null
  increasePercent: string | null
}

type ExistingPeriod = {
  start: string
  end: string
  // Null for a percentage increase set in Ads Manager.
  increaseAmount: string | null
  value: string
}

type CheckedPeriod = BudgetPeriod & { problem: string | null }

export type ScheduleCheck = {
  unavailable: boolean
  currency: string | null
  timeZone: string | null
  // The account's local time when the card was prepared.
  now: string | null
  dailyBudget: string | null
  problems: string[]
  existingCount: number
  existing: ExistingPeriod[]
  periods: CheckedPeriod[]
}

export type BudgetScheduleArgs = {
  type: ScheduleObjectType
  id: string
  accountId: string
  name: string
  scope: string | null
  periods: BudgetPeriod[]
  check: ScheduleCheck | null
}

const REFERENCES = [
  { key: "campaign", type: "campaign", idKey: "campaign_id" },
  { key: "ad_set", type: "adset", idKey: "adset_id" },
] as const

export const SCHEDULE_OBJECT_TITLES = { campaign: "Campaign", adset: "Ad Set" } as const
const LOCAL_TIME = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/
const MIN_HOURS = 3
// The daily budget plus the increase can be at most this multiple of the daily budget.
const MAX_MULTIPLE = 8
const MAX_PERIODS = 50

export function parseBudgetScheduleArgs(value: unknown): BudgetScheduleArgs | null {
  if (!isRecord(value) || !Array.isArray(value["periods"])) return null
  const present = REFERENCES.filter((reference) => isRecord(value[reference.key]))
  const [reference] = present
  if (reference === undefined || present.length !== 1) return null
  const target = value[reference.key] as Record<string, unknown>
  const id = target[reference.idKey]
  if (!isNonEmptyString(id)) return null
  const periods: BudgetPeriod[] = []
  for (const item of value["periods"]) {
    const period = parsePeriod(item)
    if (period === null) return null
    periods.push(period)
  }
  return {
    type: reference.type,
    id,
    accountId: typeof target["account_id"] === "string" ? target["account_id"] : "",
    name: isNonEmptyString(target["label"]) ? target["label"] : id,
    scope: isNonEmptyString(target["scope_label"]) ? target["scope_label"] : null,
    periods,
    check: parseCheck(value["_schedule_checks"]),
  }
}

function parsePeriod(value: unknown): BudgetPeriod | null {
  if (!isRecord(value) || typeof value["start"] !== "string" || typeof value["end"] !== "string")
    return null
  const amount = value["increase_amount"]
  const percent = value["increase_percent"]
  return {
    start: value["start"],
    end: value["end"],
    increaseAmount: typeof amount === "string" ? amount : null,
    increasePercent:
      typeof percent === "number" || typeof percent === "string" ? String(percent) : null,
  }
}

function parseCheck(value: unknown): ScheduleCheck | null {
  if (!isRecord(value)) return null
  const text = (key: string) => (isNonEmptyString(value[key]) ? value[key] : null)
  const list = (key: string) => (Array.isArray(value[key]) ? (value[key] as unknown[]) : [])
  const existing = list("existing").flatMap((item) =>
    isRecord(item) &&
    typeof item["start"] === "string" &&
    typeof item["end"] === "string" &&
    typeof item["value"] === "string"
      ? [
          {
            start: item["start"],
            end: item["end"],
            increaseAmount: isNonEmptyString(item["increase_amount"])
              ? item["increase_amount"]
              : null,
            value: item["value"],
          },
        ]
      : []
  )
  const periods = list("periods").flatMap((item) => {
    const period = parsePeriod(item)
    if (period === null || !isRecord(item)) return []
    return [{ ...period, problem: isNonEmptyString(item["problem"]) ? item["problem"] : null }]
  })
  const count = value["existing_count"]
  return {
    unavailable: value["unavailable"] === true,
    currency: text("currency"),
    timeZone: text("time_zone"),
    now: text("now"),
    dailyBudget: text("daily_budget"),
    problems: list("problems").filter(isNonEmptyString),
    existingCount: typeof count === "number" && Number.isSafeInteger(count) ? count : 0,
    existing,
    periods,
  }
}

/** Minutes since the epoch for a local YYYY-MM-DDTHH:MM time, read as if it were UTC. */
function minutes(value: string): number | null {
  const match = LOCAL_TIME.exec(value)
  if (!match) return null
  const [, year, month, day, hour, minute] = match.map(Number) as [number, ...number[]]
  const time = Date.UTC(year ?? 0, (month ?? 1) - 1, day, hour, minute)
  const date = new Date(time)
  // Rejects dates such as 31 February, which Date would roll into March.
  if (date.getUTCDate() !== day || date.getUTCMonth() !== (month ?? 1) - 1) return null
  return time / 60_000
}

function minor(amount: string): number | null {
  return isBudgetAmount(amount) ? Math.round(Number(amount.trim()) * 100) : null
}

/** The increase in currency units: the amount, or the percentage of today's daily budget. */
function increaseOf(period: BudgetPeriod, dailyBudget: string | null): number | null {
  if (period.increaseAmount !== null) {
    const value = minor(period.increaseAmount)
    return value === null ? null : value / 100
  }
  const percent = Number(period.increasePercent)
  const daily = dailyBudget === null ? null : minor(dailyBudget)
  if (!Number.isInteger(percent) || percent < 1 || percent > 700 || daily === null) return null
  // Rounded down to whole cents, as the server does.
  return Math.floor((daily * percent) / 100) / 100
}

/** Why each period can't be added, judged against Meta's rules and the periods before it. */
export function periodProblems(args: BudgetScheduleArgs): (string | null)[] {
  const check = args.check
  const taken: { start: string; end: string }[] = [...(check?.existing ?? [])]
  let unchanged = true
  return args.periods.map((period, index) => {
    const shown = check?.periods[index]
    // The server's verdict holds while this period and those before it are as it judged them.
    unchanged &&= shown !== undefined && samePeriod(shown, period)
    const problem = unchanged && shown?.problem ? shown.problem : ruleProblem(period, check, taken)
    if (problem === null) taken.push(period)
    return problem
  })
}

function ruleProblem(
  period: BudgetPeriod,
  check: ScheduleCheck | null,
  taken: readonly { start: string; end: string }[]
): string | null {
  const start = minutes(period.start)
  const end = minutes(period.end)
  if (start === null || end === null) return "Enter a real date and time for the start and end."
  const now = check?.now ? minutes(check.now) : null
  if (now !== null && start <= now) return "Start this period in the future."
  if (end - start < MIN_HOURS * 60) return "Make this period at least 3 hours long."
  const increase = increaseOf(period, check?.dailyBudget ?? null)
  if (increase === null)
    return period.increaseAmount !== null
      ? "Enter an increase above zero, with at most two decimal places."
      : "Enter a whole percentage from 1 to 700."
  const daily = check?.dailyBudget ? Number(check.dailyBudget) : null
  if (daily !== null && increase > daily * (MAX_MULTIPLE - 1) + 1e-9)
    return `Meta allows a budget of at most ${String(MAX_MULTIPLE)} times the daily budget, so the increase can be at most ${budgetMoney((daily * (MAX_MULTIPLE - 1)).toFixed(2), check?.currency ?? null)}.`
  const overlap = taken.find((other) => {
    const otherStart = minutes(other.start)
    const otherEnd = minutes(other.end)
    return otherStart !== null && otherEnd !== null && start < otherEnd && otherStart < end
  })
  if (overlap)
    return `This period overlaps the one from ${formatLocalTime(overlap.start)} to ${formatLocalTime(overlap.end)}.`
  return null
}

function samePeriod(left: BudgetPeriod, right: BudgetPeriod): boolean {
  return (
    left.start === right.start &&
    left.end === right.end &&
    left.increaseAmount === right.increaseAmount &&
    left.increasePercent === right.increasePercent
  )
}

/** Why the periods can't be approved yet, or null. */
export function budgetScheduleProblem(args: BudgetScheduleArgs | null): string | null {
  if (args === null) return null
  if (args.periods.length === 0) return "Switch on at least one period, or decline this request."
  const check = args.check
  if (check?.problems.length) return check.problems[0] ?? null
  if (check !== null && check.existingCount + args.periods.length > MAX_PERIODS)
    return `Meta allows ${String(MAX_PERIODS)} periods on a campaign or ad set, and this one already has ${String(check.existingCount)}.`
  if (periodProblems(args).some((problem) => problem !== null))
    return "Change or leave out the periods Meta won't accept, or decline this request."
  return null
}

export type PeriodRow = { period: BudgetPeriod; included: boolean }

/** Each proposed period with its edited version, or left out; edits keep the proposal's order. */
export function periodRows(proposed: BudgetScheduleArgs, current: BudgetScheduleArgs): PeriodRow[] {
  if (current.periods.length > proposed.periods.length)
    return current.periods.map((period) => ({ period, included: true }))
  let next = 0
  return proposed.periods.map((period, index) => {
    const kept = current.periods[next]
    const rest = proposed.periods.length - index <= current.periods.length - next
    // An edited period matches no later proposed one, so it belongs here.
    const included =
      kept !== undefined &&
      (rest ||
        samePeriod(kept, period) ||
        !proposed.periods.slice(index + 1).some((later) => samePeriod(kept, later)))
    if (!included) return { period, included }
    next += 1
    return { period: kept, included }
  })
}

/** The `periods` argument after editing one row, or switching it on or off. */
export function editPeriods(
  rows: readonly PeriodRow[],
  index: number,
  edit: Partial<BudgetPeriod> | { included: boolean }
): Record<string, unknown>[] {
  return rows.flatMap((row, at) => {
    if (at !== index) return row.included ? [periodArg(row.period)] : []
    if ("included" in edit) return edit.included ? [periodArg(row.period)] : []
    return [periodArg({ ...row.period, ...edit })]
  })
}

function periodArg(period: BudgetPeriod): Record<string, unknown> {
  return {
    start: period.start,
    end: period.end,
    ...(period.increaseAmount !== null
      ? { increase_amount: period.increaseAmount }
      : { increase_percent: Number(period.increasePercent) }),
  }
}

/** The highest daily budget during the periods that can be added, in currency units. */
export function highestBudget(args: BudgetScheduleArgs): number | null {
  const daily = args.check?.dailyBudget ? Number(args.check.dailyBudget) : null
  if (daily === null) return null
  const problems = periodProblems(args)
  const increases = args.periods.flatMap((period, index) => {
    const increase = problems[index] === null ? increaseOf(period, daily.toString()) : null
    return increase === null ? [] : [increase]
  })
  return increases.length > 0 ? daily + Math.max(...increases) : null
}

type TimelineBar = { left: number; width: number; tone: "existing" | "new" | "blocked" }

export type ScheduleTimeline = {
  from: string
  to: string
  now: TimelineBar[]
  after: TimelineBar[]
}

/** Existing and new periods as bars across the dates they span, in percent of the width. */
export function scheduleTimeline(args: BudgetScheduleArgs): ScheduleTimeline | null {
  const span = (period: { start: string; end: string }) => {
    const start = minutes(period.start)
    const end = minutes(period.end)
    return start !== null && end !== null && start < end ? { start, end } : null
  }
  const existing = (args.check?.existing ?? []).flatMap((period) => {
    const times = span(period)
    return times ? [{ ...times, tone: "existing" as const }] : []
  })
  const problems = periodProblems(args)
  const added = args.periods.flatMap((period, index) => {
    const times = span(period)
    const tone = problems[index] === null ? ("new" as const) : ("blocked" as const)
    return times ? [{ ...times, tone }] : []
  })
  const all = [...existing, ...added]
  if (all.length === 0) return null
  const from = Math.min(...all.map((bar) => bar.start))
  const to = Math.max(...all.map((bar) => bar.end))
  const bar = ({ start, end, tone }: (typeof all)[number]): TimelineBar => ({
    left: ((start - from) / (to - from)) * 100,
    width: ((end - start) / (to - from)) * 100,
    tone,
  })
  const day = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" })
  return {
    from: day.format(new Date(from * 60_000)),
    to: day.format(new Date(to * 60_000)),
    now: existing.map(bar),
    after: all.map(bar),
  }
}

/** A local YYYY-MM-DDTHH:MM time as "Fri 27 Nov 2026, 00:00", without shifting its zone. */
export function formatLocalTime(value: string): string {
  const at = minutes(value)
  if (at === null) return value
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(new Date(at * 60_000))
}

/** One line for a period: its times and how much the budget rises. */
export function periodSummary(period: BudgetPeriod, check: ScheduleCheck | null): string {
  const times = `${formatLocalTime(period.start)} → ${formatLocalTime(period.end)}`
  const increase = increaseOf(period, check?.dailyBudget ?? null)
  const amount =
    increase === null ? null : budgetMoney(increase.toFixed(2), check?.currency ?? null)
  if (period.increasePercent !== null)
    return `${times} · +${period.increasePercent}%${amount ? ` (${amount})` : ""}`
  return `${times} · +${amount ?? period.increaseAmount ?? ""}`
}

export function existingSummary(period: ExistingPeriod, currency: string | null): string {
  const times = `${formatLocalTime(period.start)} → ${formatLocalTime(period.end)}`
  if (period.increaseAmount !== null)
    return `${times} · +${budgetMoney(period.increaseAmount, currency)}`
  return `${times} · Percentage increase (${period.value})`
}

export function budgetScheduleDetails(args: BudgetScheduleArgs | null): FanOutDetail[] {
  if (args === null) return []
  return [{ label: "Periods", value: String(args.periods.length) }]
}

// Result models

type PeriodOutcomeToken = "added" | "failed" | "unverified"

type PeriodResultRow = {
  start: string
  end: string
  increaseAmount: string
  increasePercent: number | null
  outcome: PeriodOutcomeToken
  errorCode: string | null
  message: string | null
}

export type BudgetScheduleResult = {
  currency: string
  timeZone: string
  name: string
  dailyBudget: string
  periods: PeriodResultRow[]
}

const OUTCOMES = new Set<string>(["added", "failed", "unverified"])

export function parseBudgetScheduleResult(value: unknown): BudgetScheduleResult | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value["currency"]) ||
    !isNonEmptyString(value["time_zone"]) ||
    !isNonEmptyString(value["object_id"]) ||
    !isNonEmptyString(value["daily_budget"]) ||
    !Array.isArray(value["periods"])
  )
    return null
  const periods: PeriodResultRow[] = []
  for (const item of value["periods"]) {
    if (
      !isRecord(item) ||
      typeof item["start"] !== "string" ||
      typeof item["end"] !== "string" ||
      !isNonEmptyString(item["increase_amount"]) ||
      typeof item["outcome"] !== "string" ||
      !OUTCOMES.has(item["outcome"])
    )
      return null
    const text = (key: string) => (typeof item[key] === "string" ? item[key] : null)
    periods.push({
      start: item["start"],
      end: item["end"],
      increaseAmount: item["increase_amount"],
      increasePercent:
        typeof item["increase_percent"] === "number" ? item["increase_percent"] : null,
      outcome: item["outcome"] as PeriodOutcomeToken,
      errorCode: text("error_code"),
      message: text("message"),
    })
  }
  return {
    currency: value["currency"],
    timeZone: value["time_zone"],
    name: isNonEmptyString(value["object_name"]) ? value["object_name"] : value["object_id"],
    dailyBudget: value["daily_budget"],
    periods,
  }
}
