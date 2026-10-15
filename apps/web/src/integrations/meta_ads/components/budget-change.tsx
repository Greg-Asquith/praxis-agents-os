// apps/web/src/integrations/meta_ads/components/budget-change.tsx

import { CircleAlertIcon, TriangleAlertIcon } from "lucide-react"

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import {
  MetaAdsLink,
  MetaAdsOutcomeTable,
  type MetaAdsOutcomeRow,
} from "@/integrations/meta_ads/components/outcome-table"
import { adsManagerObjectUrl } from "@/integrations/meta_ads/lib/ads-manager-link"
import {
  BUDGET_OBJECT_TITLES,
  budgetKindSuffix,
  budgetMoney,
  budgetNotes,
  budgetRowKey,
  budgetRows,
  dailyTotal,
  editBudgets,
  isBudgetAmount,
  type BudgetChangeArgs,
  type BudgetChangeResult,
  type BudgetRow,
} from "@/integrations/meta_ads/lib/budget-change"
import { currencySymbol, formatCurrency, formatPercentageChange, pluralize } from "@/lib/format"

export function BudgetApprovalSummary({
  args,
  disabled,
  onFieldEdit,
  proposed,
}: {
  args: BudgetChangeArgs
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
  proposed: BudgetChangeArgs
}) {
  const rows = budgetRows(proposed, args)
  const kept = rows.filter((row) => row.included).length
  const total = dailyTotal(rows)
  const edit = (key: string, change: { amount: string } | { included: boolean }) => {
    onFieldEdit("updates", editBudgets(rows, key, change))
  }
  return (
    <div className="grid min-w-0 gap-3">
      <div
        className="border-warning/40 bg-warning/10 flex flex-wrap items-center justify-between gap-3 rounded-lg border px-3 py-2.5"
        role="note"
      >
        <div className="grid gap-0.5">
          <p className="text-warning-text flex items-center gap-2 text-sm font-medium">
            <TriangleAlertIcon aria-hidden="true" className="size-4 shrink-0" />
            Changes take effect straight away
          </p>
          <p className="text-muted-foreground text-sm">
            {String(kept)} {pluralize(kept, "budget")}
          </p>
        </div>
        {total ? (
          <div className="text-right">
            <p className="text-muted-foreground text-sm">Daily total</p>
            <p className="text-lg font-semibold tabular-nums">
              {formatCurrency(total.before, total.currency)} →{" "}
              {formatCurrency(total.after, total.currency)}
            </p>
          </div>
        ) : null}
      </div>
      <ul
        aria-label="Proposed budget changes"
        className="divide-y overflow-hidden rounded-lg border"
      >
        {rows.map((row) => (
          <li key={budgetRowKey(row.change)} className="min-w-0 p-3">
            <BudgetItem disabled={disabled} edit={edit} row={row} />
          </li>
        ))}
      </ul>
      <p className="text-muted-foreground text-sm">Untick a row to leave that budget as it is.</p>
    </div>
  )
}

function BudgetItem({
  disabled,
  edit,
  row,
}: {
  disabled: boolean
  edit: (key: string, change: { amount: string } | { included: boolean }) => void
  row: BudgetRow
}) {
  const { change, included } = row
  const key = budgetRowKey(change)
  const valid = isBudgetAmount(change.amount)
  const symbol = change.currency ? currencySymbol(change.currency) : null
  const previous = change.previousAmount === null ? null : Number(change.previousAmount)
  const percent =
    previous !== null && valid ? formatPercentageChange(previous, Number(change.amount)) : "—"
  const problem = included ? (change.check?.problem ?? null) : null
  const href = adsManagerObjectUrl(change.type, change.accountId, change.id)
  return (
    <div className="grid min-w-0 gap-2">
      <div className="flex min-w-0 items-start gap-3">
        <Checkbox
          aria-label={`Include ${change.name}`}
          checked={included}
          className="mt-0.5"
          disabled={disabled}
          onCheckedChange={(checked) => {
            edit(key, { included: checked })
          }}
        />
        <div className="grid min-w-0 flex-1 gap-0.5">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium wrap-anywhere">{change.name}</p>
            <Badge variant="secondary">{BUDGET_OBJECT_TITLES[change.type]}</Badge>
          </div>
          {change.scope ? <p className="text-muted-foreground text-sm">{change.scope}</p> : null}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 pl-7 tabular-nums">
        {change.previousAmount !== null ? (
          <span className="text-muted-foreground text-sm line-through">
            {budgetMoney(change.previousAmount, change.currency)}
          </span>
        ) : null}
        <div className="flex items-center gap-1.5">
          {symbol ? <span className="text-muted-foreground text-sm">{symbol}</span> : null}
          <Input
            aria-invalid={included && !valid}
            aria-label={`New budget for ${change.name}`}
            className="w-28"
            disabled={disabled || !included}
            inputMode="decimal"
            onChange={(event) => {
              edit(key, { amount: event.currentTarget.value })
            }}
            value={change.amount}
          />
          <span className="text-muted-foreground text-sm">{budgetKindSuffix(change.kind)}</span>
        </div>
        {included && percent !== "—" ? (
          <Badge variant={Number(change.amount) < (previous ?? 0) ? "secondary" : "success"}>
            {percent}
          </Badge>
        ) : null}
      </div>
      {included && !valid ? (
        <p className="text-destructive pl-7 text-sm">
          Enter an amount above zero, with at most two decimal places.
        </p>
      ) : null}
      {problem ? (
        <p className="text-destructive flex items-start gap-2 pl-7 text-sm font-medium">
          <CircleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          {problem}
        </p>
      ) : null}
      {included
        ? budgetNotes(change).map((note) => (
            <p key={note} className="text-muted-foreground pl-7 text-sm">
              {note}
            </p>
          ))
        : null}
      {href ? (
        <div className="pl-7">
          <MetaAdsLink href={href}>Open in Ads Manager</MetaAdsLink>
        </div>
      ) : null}
    </div>
  )
}

export function BudgetOutcome({ result }: { result: BudgetChangeResult }) {
  const money = (amount: string | null) => (amount ? budgetMoney(amount, result.currency) : "—")
  const rows: MetaAdsOutcomeRow[] = result.budgets.map((row) => {
    const applied = row.outcome === "failed" ? null : row.amount
    return {
      name: row.name,
      before: money(row.previousAmount),
      after: money(applied),
      change: applied ? formatPercentageChange(Number(row.previousAmount), Number(applied)) : "—",
      outcome: row.outcome,
      details: row.message ?? "",
      errorCode: row.errorCode,
    }
  })
  return (
    <MetaAdsOutcomeTable
      columns={[
        { key: "name", kind: "text", label: "Name" },
        { key: "before", kind: "text", label: "Before", align: "right" },
        { key: "after", kind: "text", label: "After", align: "right" },
        { key: "change", kind: "text", label: "Change", align: "right" },
      ]}
      exportFilename="meta-ads-budgets.csv"
      rows={rows}
    />
  )
}
