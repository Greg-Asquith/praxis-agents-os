// apps/web/src/integrations/meta_ads/components/budget-schedule.tsx

import { CircleAlertIcon } from "lucide-react"

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { MoneyField } from "@/integrations/meta_ads/components/campaign-money-field"
import {
  SelectField,
  SwitchField,
  TextField,
} from "@/integrations/meta_ads/components/campaign-controls"
import { ChangeBanner } from "@/integrations/meta_ads/components/change-banner"
import {
  MetaAdsLink,
  MetaAdsOutcomeTable,
  type MetaAdsOutcomeRow,
} from "@/integrations/meta_ads/components/outcome-table"
import { SettingRow, SettingRows } from "@/integrations/meta_ads/components/setting-rows"
import { adsManagerObjectUrl } from "@/integrations/meta_ads/lib/ads-manager-link"
import { budgetMoney } from "@/integrations/meta_ads/lib/budget-change"
import {
  SCHEDULE_OBJECT_TITLES,
  editPeriods,
  existingSummary,
  formatLocalTime,
  highestBudget,
  periodProblems,
  periodRows,
  periodSummary,
  scheduleTimeline,
  type BudgetPeriod,
  type BudgetScheduleArgs,
  type BudgetScheduleResult,
  type PeriodRow as Row,
  type ScheduleCheck,
  type ScheduleTimeline,
} from "@/integrations/meta_ads/lib/budget-schedule"
import { pluralize } from "@/lib/format"
import { cn } from "@/lib/utils"

type Edit = (index: number, change: Partial<BudgetPeriod> | { included: boolean }) => void

const INCREASE_KINDS = [
  { value: "amount", label: "Fixed Amount" },
  { value: "percent", label: "Percentage" },
] as const

const BAR_TONES = {
  existing: "bg-muted-foreground/50",
  new: "bg-primary",
  blocked: "bg-destructive",
} as const

export function BudgetScheduleApproval({
  args,
  disabled,
  onFieldEdit,
  proposed,
}: {
  args: BudgetScheduleArgs
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
  proposed: BudgetScheduleArgs
}) {
  const check = args.check
  const currency = check?.currency ?? null
  const rows = periodRows(proposed, args)
  const problems = periodProblems(args)
  const highest = highestBudget(args)
  const timeline = scheduleTimeline(args)
  const href = adsManagerObjectUrl(args.type, args.accountId, args.id)
  const edit: Edit = (index, change) => {
    onFieldEdit("periods", editPeriods(rows, index, change))
  }
  return (
    <div className="grid min-w-0 gap-3">
      <ChangeBanner
        aside={
          check?.dailyBudget ? (
            <div className="text-right tabular-nums">
              <p className="text-muted-foreground text-sm">Daily Budget</p>
              <p className="text-lg font-semibold">
                {budgetMoney(check.dailyBudget, currency)}
                {highest !== null ? ` → up to ${budgetMoney(highest.toFixed(2), currency)}` : ""}
              </p>
            </div>
          ) : null
        }
        detail={[
          args.name,
          SCHEDULE_OBJECT_TITLES[args.type],
          `${String(args.periods.length)} of ${String(rows.length)} ${pluralize(rows.length, "period")}`,
        ].join(" · ")}
        title="Spend goes up during these periods"
      />
      {check?.unavailable ? (
        <p className="text-warning-text text-sm">
          This budget couldn&apos;t be checked before approval, so it can&apos;t be scheduled.
        </p>
      ) : null}
      {check?.problems.map((problem) => (
        <p key={problem} className="text-destructive flex items-start gap-2 text-sm font-medium">
          <CircleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          {problem}
        </p>
      ))}
      <SettingRows ariaLabel="Budget increases" defaultOpen="period-0">
        {rows.map((row, index) => (
          <PeriodRow
            // eslint-disable-next-line react-x/no-array-index-key -- Periods have no ID until Meta adds them, and a key from their values would remount the row, and lose focus, on each edit.
            key={index}
            check={check}
            disabled={disabled}
            edit={edit}
            index={index}
            // The period's place in `args.periods` while it is switched on.
            problem={
              row.included
                ? (problems[rows.slice(0, index).filter((other) => other.included).length] ?? null)
                : null
            }
            row={row}
          />
        ))}
        {check?.existing.length ? (
          <SettingRow
            rowKey="existing"
            summary={`${String(check.existing.length)} ${pluralize(check.existing.length, "period")}`}
            title="Already Scheduled"
          >
            <ul className="grid gap-1 text-sm">
              {check.existing.map((period) => (
                <li key={`${period.start}-${period.end}`}>{existingSummary(period, currency)}</li>
              ))}
            </ul>
          </SettingRow>
        ) : null}
      </SettingRows>
      {timeline ? <Timeline timeline={timeline} /> : null}
      <p className="text-muted-foreground text-sm">
        {check?.timeZone ? `Times are in ${check.timeZone}. ` : ""}After each period the budget goes
        back to its daily amount.
      </p>
      {href ? <MetaAdsLink href={href}>Open in Ads Manager</MetaAdsLink> : null}
    </div>
  )
}

function PeriodRow({
  check,
  disabled,
  edit,
  index,
  problem,
  row,
}: {
  check: ScheduleCheck | null
  disabled: boolean
  edit: Edit
  index: number
  problem: string | null
  row: Row
}) {
  const { period, included } = row
  const currency = check?.currency ?? null
  const percent = period.increasePercent !== null
  const summary = !included ? "Left out" : (problem ?? periodSummary(period, check))
  return (
    <SettingRow
      rowKey={`period-${String(index)}`}
      summary={summary}
      title={`Period ${String(index + 1)}`}
      tone={problem ? "error" : "neutral"}
    >
      <SwitchField
        checked={included}
        disabled={disabled}
        label="Add This Period"
        onChange={(checked) => {
          edit(index, { included: checked })
        }}
      />
      {included ? (
        <>
          <div className="grid min-w-0 gap-3 sm:grid-cols-2">
            <TextField
              disabled={disabled}
              label="Starts"
              onChange={(start) => {
                edit(index, { start })
              }}
              type="datetime-local"
              value={period.start}
            />
            <TextField
              disabled={disabled}
              label="Ends"
              onChange={(end) => {
                edit(index, { end })
              }}
              type="datetime-local"
              value={period.end}
            />
            <SelectField
              disabled={disabled}
              label="Increase By"
              onChange={(kind) => {
                edit(
                  index,
                  kind === "percent"
                    ? { increaseAmount: null, increasePercent: period.increasePercent ?? "50" }
                    : { increaseAmount: period.increaseAmount ?? "", increasePercent: null }
                )
              }}
              options={INCREASE_KINDS}
              value={percent ? "percent" : "amount"}
            />
            <MoneyField
              currency={percent ? null : currency}
              disabled={disabled}
              invalid={problem !== null}
              label="Increase"
              onChange={(value) => {
                edit(index, percent ? { increasePercent: value } : { increaseAmount: value })
              }}
              suffix={percent ? "%" : undefined}
              value={(percent ? period.increasePercent : period.increaseAmount) ?? ""}
            />
          </div>
          {problem ? <p className="text-destructive text-sm font-medium">{problem}</p> : null}
        </>
      ) : null}
    </SettingRow>
  )
}

/** Existing periods now, and with the new ones added, across the dates they span. */
function Timeline({ timeline }: { timeline: ScheduleTimeline }) {
  const strips = [
    { title: "Now", bars: timeline.now },
    { title: "After", bars: timeline.after },
  ]
  return (
    <div className="grid min-w-0 gap-1">
      {strips.map(({ title, bars }) => (
        <div key={title} className="flex items-center gap-2">
          <span className="text-muted-foreground w-10 text-xs font-medium">{title}</span>
          <div
            aria-label={`${title}: ${String(bars.length)} ${pluralize(bars.length, "period")} from ${timeline.from} to ${timeline.to}`}
            className="bg-muted relative h-2.5 flex-1 rounded-[2px]"
            role="img"
          >
            {bars.map((bar) => (
              <span
                key={`${String(bar.left)}-${String(bar.width)}-${bar.tone}`}
                className={cn("absolute inset-y-0 rounded-[2px]", BAR_TONES[bar.tone])}
                style={{ left: `${String(bar.left)}%`, width: `max(2px, ${String(bar.width)}%)` }}
              />
            ))}
          </div>
        </div>
      ))}
      <div className="text-muted-foreground ml-12 flex justify-between text-xs">
        <span>{timeline.from}</span>
        <span>{timeline.to}</span>
      </div>
      <div className="text-muted-foreground ml-12 flex flex-wrap gap-x-3 gap-y-1 text-xs">
        <Legend tone="existing">Already Scheduled</Legend>
        <Legend tone="new">New</Legend>
        <Legend tone="blocked">Can&apos;t Be Added</Legend>
      </div>
    </div>
  )
}

function Legend({ children, tone }: { children: string; tone: keyof typeof BAR_TONES }) {
  return (
    <span className="flex items-center gap-1.5">
      <span aria-hidden="true" className={cn("size-2.5 rounded-[2px]", BAR_TONES[tone])} />
      {children}
    </span>
  )
}

export function BudgetScheduleOutcome({ result }: { result: BudgetScheduleResult }) {
  const rows: MetaAdsOutcomeRow[] = result.periods.map((period) => ({
    starts: formatLocalTime(period.start),
    ends: formatLocalTime(period.end),
    increase:
      `+${budgetMoney(period.increaseAmount, result.currency)}` +
      (period.increasePercent !== null ? ` (${String(period.increasePercent)}%)` : ""),
    outcome: period.outcome,
    details: period.message ?? "",
    errorCode: period.errorCode,
  }))
  return (
    <div className="grid min-w-0 gap-2">
      <p className="text-muted-foreground text-sm">
        {result.name}: daily budget {budgetMoney(result.dailyBudget, result.currency)}. Times are in{" "}
        {result.timeZone}.
      </p>
      <MetaAdsOutcomeTable
        columns={[
          { key: "starts", kind: "text", label: "Starts" },
          { key: "ends", kind: "text", label: "Ends" },
          { key: "increase", kind: "text", label: "Increase", align: "right" },
        ]}
        exportFilename="meta-ads-budget-increases.csv"
        rows={rows}
      />
    </div>
  )
}
