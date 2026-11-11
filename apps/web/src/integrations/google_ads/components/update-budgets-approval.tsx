// apps/web/src/integrations/google_ads/components/update-budgets-approval.tsx

import { ArrowRightIcon, XIcon } from "lucide-react"
import { useMemo, useState } from "react"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-types"
import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DataTable,
  type DataColumn,
  type DataRow,
  type DataTableTab,
} from "@/components/ui/data-table"
import { AttentionLine } from "@/integrations/ads/components/attention-line"
import { ChangeBanner } from "@/integrations/ads/components/change-banner"
import { ChangeSummary } from "@/integrations/ads/components/change-summary"
import { CommittedInput } from "@/integrations/ads/components/committed-input"
import { SegmentedChoice } from "@/integrations/ads/components/controls"
import { EntitySearch } from "@/integrations/ads/components/entity-search"
import { ParentTable } from "@/integrations/ads/components/parent-table"
import { CheckChanges } from "@/integrations/google_ads/components/check-changes"
import { moneyInput } from "@/integrations/google_ads/lib/campaign-bidding"
import { scaledMoney } from "@/integrations/google_ads/lib/update-ad-groups"
import {
  budgetCounts,
  budgetCurrency,
  budgetKindText,
  budgetParents,
  budgetRows,
  budgetsBannerDetail,
  budgetsNeedCheck,
  cancelledBudgetChanges,
  dailyDelta,
  DAYS_PER_MONTH,
  DELIVERIES,
  DELIVERY_LABELS,
  editedBudgetChanges,
  monthAtAmount,
  moneyText,
  parseCancelledBudgetChanges,
  totalDailyDelta,
  withAmount,
  withDelivery,
  withSharedBudget,
  type BudgetRow,
  type CancelledBudgetChange,
  type UpdateBudgetsArgs,
} from "@/integrations/google_ads/lib/update-budgets"
import { currencySymbol, formatCurrency, formatPercentageChange } from "@/lib/format"
import { isRecord } from "@/lib/guards"

const TOOL_NAME = "google_ads_update_budgets"
// Below this many changes the summary and the table tools only add noise.
const TOOLS_FROM = 10

const COLUMNS: DataColumn[] = [
  { key: "name", kind: "text", label: "Campaign or Budget", width: 220 },
  { key: "budget", kind: "text", label: "Budget", width: 170 },
  { key: "amount", kind: "text", label: "Daily Amount", width: 230 },
  { key: "change", kind: "text", label: "Change", width: 90 },
  { key: "spend", kind: "text", label: "Spent This Month", width: 130 },
  { key: "month", kind: "text", label: "Month at New Amount", width: 150 },
  { key: "monthly", kind: "text", label: "Est. Monthly", width: 120 },
  { key: "cancel", kind: "text", label: "Cancel", width: 80 },
]

const PARENT_COLUMNS: DataColumn[] = [
  { key: "budget", kind: "text", label: "Budget", width: 220 },
  { key: "problems", kind: "text", label: "Problems", width: 130 },
]

const DELIVERY_OPTIONS = DELIVERIES.map((value) => ({ value, label: DELIVERY_LABELS[value] }))

type Ids = Iterable<string>

export function UpdateBudgetsApproval({
  args,
  checked,
  controls,
  disabled,
  onFieldEdit,
}: {
  args: UpdateBudgetsArgs
  // The request Google last answered for.
  checked: UpdateBudgetsArgs
  controls: ToolApprovalDecisionControls
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const [tab, setTab] = useState("all")
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set())
  const cancelled = useMemo(
    () => parseCancelledBudgetChanges(controls.retained),
    [controls.retained]
  )
  const rows = useMemo(() => budgetRows(args, checked, cancelled), [args, checked, cancelled])
  const byId = useMemo(() => new Map(rows.map((row) => [row.id, row])), [rows])
  const counts = budgetCounts(rows)
  const tools = rows.length >= TOOLS_FROM
  const live = rows.filter((row) => !row.cancelled)
  const accountIds = [...new Set(live.map((row) => row.customerId))]
  const [firstAccount] = accountIds
  const currency = args.accounts.get(firstAccount ?? "")?.currencyCode ?? null
  const [parent, setParent] = useState<string | null>(null)
  const parents = budgetParents(rows, args.accounts, accountIds.length > 1)
  const shown = parent === null ? rows : rows.filter((row) => row.id === parent)

  // A review redraws the card, so cancelled changes live beside the request for Undo.
  const save = (
    changes: Record<string, unknown>[],
    nextCancelled: readonly CancelledBudgetChange[]
  ) => {
    if (nextCancelled !== cancelled) controls.onRetain?.(nextCancelled)
    onFieldEdit("changes", changes)
  }
  const setAmounts = (ids: Ids, amount: (row: BudgetRow) => string | null) => {
    save(
      editedBudgetChanges(args, new Set(ids), (change) => {
        const value = byId.get(change.key)
        const next = value ? amount(value) : null
        return next ? withAmount(change, next) : change.entry
      }),
      cancelled
    )
  }
  const scaleBy = (ids: Ids, percent: number) => {
    setAmounts(ids, (row) => {
      const was = row.was?.amount
      return row.sharedBudget === null && was
        ? scaledMoney(was, percent, budgetCurrency(args, row))
        : null
    })
  }
  const cancel = (ids: Ids) => {
    const { cancelled: items, changes } = cancelledBudgetChanges(args, new Set(ids))
    save(changes, [...cancelled, ...items])
  }
  const undo = (key: string) => {
    const item = cancelled.find((entry) => entry.key === key)
    if (item)
      save(
        [...args.changes.map((change) => change.entry), item.entry],
        cancelled.filter((entry) => entry !== item)
      )
  }
  const liveIds = (match: (row: BudgetRow) => boolean) => live.filter(match).map((row) => row.id)
  const raised = liveIds((row) => (dailyDelta(row) ?? 0) > 0)
  const attention = liveIds((row) => row.problem !== null)
  const daily = totalDailyDelta(rows)

  return (
    <div className="grid min-w-0 gap-3">
      <ChangeBanner
        aside={
          daily !== 0 ? (
            <div className="grid text-right">
              <p className="text-sm font-medium tabular-nums">
                {signedMoney(daily, currency)} a day
              </p>
              <p className="text-muted-foreground text-xs tabular-nums">
                about {signedMoney(daily * DAYS_PER_MONTH, currency, 0)} a month
              </p>
            </div>
          ) : null
        }
        detail={budgetsBannerDetail(counts, accountIds, args.accounts)}
      />
      {tools ? (
        <>
          <ChangeSummary
            lines={[
              {
                action: (
                  <PercentInput
                    disabled={disabled}
                    label="Raise every budget in this line by a percentage"
                    onCommit={(percent) => {
                      scaleBy(raised, percent)
                    }}
                  />
                ),
                count: counts.increases,
                id: "raise",
                label: "Raise Daily Budget",
                onSelect: () => {
                  setTab("raise")
                },
                selected: tab === "raise",
              },
              {
                count: counts.decreases,
                id: "lower",
                label: "Lower Daily Budget",
                onSelect: () => {
                  setTab("lower")
                },
                selected: tab === "lower",
              },
              {
                count: counts.shared,
                detail: "every campaign on it changes",
                id: "shared",
                label: "Change a Shared Budget",
                onSelect: () => {
                  setTab("shared")
                },
                selected: tab === "shared",
              },
              {
                count: counts.moves,
                id: "move",
                label: "Move Onto a Shared Budget",
                onSelect: () => {
                  setTab("move")
                },
                selected: tab === "move",
              },
              {
                action: (
                  <Button
                    disabled={disabled}
                    onClick={() => {
                      cancel(attention)
                    }}
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    Cancel These {String(counts.problems)}
                  </Button>
                ),
                count: counts.problems,
                id: "attention",
                label: "Needs Attention",
                onSelect: () => {
                  setTab("attention")
                },
                selected: tab === "attention",
                tone: "danger",
              },
            ]}
          />
          <AttentionLine
            count={counts.problems}
            onShow={() => {
              setParent(null)
              setTab("attention")
            }}
          />
        </>
      ) : null}
      {parents.length > 1 ? (
        <ParentTable
          columns={PARENT_COLUMNS}
          disabled={disabled}
          label="Campaigns"
          onCancel={(key) => {
            cancel([key])
          }}
          onSelect={setParent}
          onUndo={undo}
          rowNoun={["campaign or budget", "campaigns and budgets"]}
          rows={parents}
          selected={parent}
        />
      ) : null}
      <DataTable
        activeTab={tab}
        columns={COLUMNS}
        exportFilename="google-ads-budget-changes.csv"
        onTabChange={setTab}
        pageSize={25}
        renderCell={(column, dataRow) => {
          const row = byId.get(String(dataRow["id"]))
          if (!row) return null
          const rowCurrency = budgetCurrency(args, row)
          if (column.key === "name") return <NameCell row={row} />
          if (column.key === "budget")
            return (
              <BudgetCell
                disabled={disabled}
                onChoose={(reference) => {
                  save(
                    editedBudgetChanges(args, new Set([row.id]), (change) =>
                      withSharedBudget(change, reference)
                    ),
                    cancelled
                  )
                }}
                row={row}
              />
            )
          if (column.key === "amount")
            return (
              <AmountCell
                currency={rowCurrency}
                disabled={disabled}
                onAmount={(amount) => {
                  setAmounts([row.id], () => amount)
                }}
                onDelivery={(value) => {
                  save(
                    editedBudgetChanges(args, new Set([row.id]), (change) =>
                      withDelivery(change, value)
                    ),
                    cancelled
                  )
                }}
                row={row}
              />
            )
          if (column.key === "change") return <ChangeBadge row={row} />
          if (column.key === "cancel")
            return (
              <CancelCell
                disabled={disabled}
                onCancel={() => {
                  cancel([row.id])
                }}
                onUndo={() => {
                  undo(row.key)
                }}
                row={row}
              />
            )
          return null
        }}
        rowClassName={(dataRow) =>
          byId.get(String(dataRow["id"]))?.cancelled ? "opacity-60" : undefined
        }
        rowDetails={false}
        rowNoun={["budget", "budgets"]}
        rows={shown.map((row) => tableRow(row, budgetCurrency(args, row)))}
        {...(tools
          ? {
              searchable: true,
              selection: {
                actions: (
                  <>
                    <CommittedInput
                      ariaLabel="Set the daily amount of every selected budget"
                      className="h-7 w-28 text-sm tabular-nums"
                      disabled={disabled}
                      onCommit={(next) => {
                        const amount = next.trim()
                        if (Number(amount) > 0) setAmounts(selected, () => amount)
                      }}
                      placeholder="Set amount"
                      value=""
                    />
                    <PercentInput
                      disabled={disabled}
                      label="Change every selected budget by a percentage"
                      onCommit={(percent) => {
                        scaleBy(selected, percent)
                      }}
                    />
                    <Button
                      disabled={disabled}
                      onClick={() => {
                        cancel(selected)
                        setSelected(new Set())
                      }}
                      size="sm"
                      type="button"
                      variant="ghost"
                    >
                      Cancel These Changes
                    </Button>
                  </>
                ),
                onChange: setSelected,
                rowId: (dataRow: DataRow) => String(dataRow["id"]),
                selected,
              },
              tabs: changeTabs(byId),
            }
          : {})}
      />
      {budgetsNeedCheck(args, checked) && args.changes.length > 0 ? (
        <CheckChanges
          canCheck
          disabled={disabled}
          label={
            [...checked.checks.values()].some((check) => check.unavailable)
              ? "Check Again"
              : "Check Changes"
          }
          note="You changed this request, so Google needs to check it again."
          onCheck={controls.onReview}
          submitting={controls.submitting}
        />
      ) : null}
    </div>
  )
}

function signedMoney(value: number, currency: string | null, digits = 2): string {
  const amount = formatCurrency(Math.abs(value), currency, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })
  return `${value < 0 ? "−" : "+"}${amount}`
}

/** The values a row exports and searches by; the cells render their own controls. */
function tableRow(row: BudgetRow, currency: string | null): DataRow {
  // A delivery change keeps the live amount.
  const amount = row.amount ?? row.was?.amount ?? null
  const monthly = amount ? Number(amount) * DAYS_PER_MONTH : null
  return {
    amount: row.sharedBudget
      ? "Shared"
      : `${moneyText(row.was?.amount ?? null, currency)} → ${moneyText(amount, currency)}`,
    budget: row.sharedBudget
      ? `${budgetKindText(row)} → ${row.sharedBudgetLabel ?? "Shared budget"}`
      : budgetKindText(row),
    cancel: "",
    change: changeText(row),
    id: row.id,
    month: row.sharedBudget ? "" : moneyText(monthAtAmount(row, amount), currency),
    monthly: row.sharedBudget ? "Shared" : moneyText(monthly, currency),
    name: row.name,
    spend: moneyText(row.spend, currency),
  }
}

function changeText(row: BudgetRow): string {
  if (row.sharedBudget) return "Move"
  const was = row.was?.amount
  if (row.amount && was) return formatPercentageChange(Number(was), Number(row.amount))
  return row.delivery ? "Delivery" : "—"
}

function changeTabs(byId: ReadonlyMap<string, BudgetRow>): DataTableTab[] {
  const live = (dataRow: DataRow, match: (row: BudgetRow) => boolean) => {
    const row = byId.get(String(dataRow["id"]))
    return row !== undefined && !row.cancelled && match(row)
  }
  const tab = (id: string, label: string, match: (row: BudgetRow) => boolean): DataTableTab => ({
    hideWhenEmpty: true,
    id,
    label,
    match: (dataRow) => live(dataRow, match),
  })
  return [
    { id: "all", label: "All", match: () => true },
    tab("raise", "Raise", (row) => (dailyDelta(row) ?? 0) > 0),
    tab("lower", "Lower", (row) => (dailyDelta(row) ?? 0) < 0),
    tab("shared", "Shared", (row) => row.sharedBudget === null && row.budget?.shared === true),
    tab("move", "Move", (row) => row.sharedBudget !== null),
    tab("attention", "Needs Attention", (row) => row.problem !== null),
  ]
}

/** The name, the problem that blocks it, and every campaign a shared budget funds. */
function NameCell({ row }: { row: BudgetRow }) {
  const funded = row.sharedBudget === null && row.budget?.shared ? row.budget : null
  return (
    <div className="grid min-w-0 gap-0.5 text-sm">
      <span className="font-medium wrap-anywhere whitespace-normal">{row.name}</span>
      {!row.cancelled && row.problem ? (
        <span className="text-destructive text-xs wrap-anywhere whitespace-normal">
          {row.problem}
        </span>
      ) : null}
      {funded && funded.campaigns.length > 0 ? (
        <details className="text-muted-foreground text-xs">
          <summary className="cursor-pointer">
            Funds {String(funded.campaignCount)}{" "}
            {funded.campaignCount === 1 ? "campaign" : "campaigns"}
          </summary>
          <ul className="mt-1 grid gap-0.5">
            {funded.campaigns.map((campaign) => (
              <li key={campaign.name} className="wrap-anywhere whitespace-normal">
                {campaign.name}
              </li>
            ))}
            {funded.campaignCount > funded.campaigns.length ? (
              <li>and {String(funded.campaignCount - funded.campaigns.length)} more</li>
            ) : null}
          </ul>
        </details>
      ) : null}
    </div>
  )
}

/** Own or shared; a move shows where the campaign goes, with a search to choose another. */
function BudgetCell({
  disabled,
  onChoose,
  row,
}: {
  disabled: boolean
  onChoose: (reference: Record<string, unknown>) => void
  row: BudgetRow
}) {
  const [searching, setSearching] = useState(false)
  if (!row.sharedBudget || row.cancelled)
    return <span className="text-sm">{budgetKindText(row)}</span>
  return (
    <div className="grid min-w-0 gap-1 text-sm">
      <span className="flex flex-wrap items-center gap-1">
        <span className="text-muted-foreground">{row.budget?.name ?? "Own"}</span>
        <ArrowRightIcon aria-hidden="true" className="text-muted-foreground size-3.5" />
        <span className="font-medium wrap-anywhere whitespace-normal">
          {row.sharedBudgetLabel ?? "Shared budget"}
        </span>
      </span>
      {row.removesBudget ? (
        <span className="text-muted-foreground text-xs">
          Its own budget is removed, since nothing else uses it.
        </span>
      ) : null}
      {searching ? (
        <EntitySearch
          disabled={disabled}
          entityKind="google_ads_campaign_budget"
          fieldKey="changes"
          label="Search shared budgets"
          onChoose={(choice) => {
            if (isRecord(choice.value)) onChoose(choice.value)
            setSearching(false)
          }}
          toolName={TOOL_NAME}
        />
      ) : (
        <Button
          className="w-fit"
          disabled={disabled}
          onClick={() => {
            setSearching(true)
          }}
          size="xs"
          type="button"
          variant="ghost"
        >
          Choose Another
        </Button>
      )}
    </div>
  )
}

/** The live amount, then the new one as an inline edit, and delivery when it changes. */
function AmountCell({
  currency,
  disabled,
  onAmount,
  onDelivery,
  row,
}: {
  currency: string | null
  disabled: boolean
  onAmount: (amount: string) => void
  onDelivery: (value: (typeof DELIVERIES)[number]) => void
  row: BudgetRow
}) {
  const was = moneyText(row.was?.amount ?? null, currency)
  if (row.sharedBudget) return <span className="text-muted-foreground text-sm">{was} → shared</span>
  if (row.cancelled)
    return (
      <span className="text-muted-foreground text-sm line-through">
        {was} → {moneyText(row.amount, currency)}
      </span>
    )
  const symbol = currency ? currencySymbol(currency) : null
  return (
    <div className="grid gap-1.5">
      {row.amount !== null ? (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground">{was} →</span>
          <div className="relative flex items-center">
            {symbol ? (
              <span
                aria-hidden="true"
                className="text-muted-foreground pointer-events-none absolute left-2 text-sm"
              >
                {symbol}
              </span>
            ) : null}
            <CommittedInput
              ariaLabel={`New daily budget for ${row.name}`}
              className={symbol ? "h-7 w-28 pl-6 text-sm tabular-nums" : "h-7 w-28 text-sm"}
              disabled={disabled}
              onCommit={(next) => {
                const amount = next.trim()
                if (Number(amount) > 0) onAmount(amount)
              }}
              value={moneyInput(row.amount)}
            />
          </div>
          {row.unchanged ? <Badge variant="secondary">Already Set</Badge> : null}
        </div>
      ) : null}
      {row.delivery !== null ? (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground">Delivery</span>
          <SegmentedChoice
            ariaLabel={`Delivery for ${row.name}`}
            compact
            disabled={disabled}
            onChange={onDelivery}
            options={DELIVERY_OPTIONS}
            value={row.delivery}
          />
        </div>
      ) : null}
    </div>
  )
}

function ChangeBadge({ row }: { row: BudgetRow }) {
  const delta = dailyDelta(row)
  const variant = row.sharedBudget
    ? "secondary"
    : delta === null || delta === 0
      ? "outline"
      : delta > 0
        ? "success"
        : "warning"
  return <Badge variant={variant}>{changeText(row)}</Badge>
}

function PercentInput({
  disabled,
  label,
  onCommit,
}: {
  disabled: boolean
  label: string
  onCommit: (percent: number) => void
}) {
  return (
    <CommittedInput
      ariaLabel={label}
      className="h-7 w-28 text-sm tabular-nums"
      disabled={disabled}
      onCommit={(next) => {
        const percent = Number(next.trim().replace(/%$/, ""))
        if (next.trim() && Number.isFinite(percent) && percent > -100) onCommit(percent)
      }}
      placeholder="Change by %"
      value=""
    />
  )
}

function CancelCell({
  disabled,
  onCancel,
  onUndo,
  row,
}: {
  disabled: boolean
  onCancel: () => void
  onUndo: () => void
  row: BudgetRow
}) {
  return row.cancelled ? (
    <Button disabled={disabled} onClick={onUndo} size="sm" type="button" variant="ghost">
      Undo
    </Button>
  ) : (
    <Button
      aria-label="Cancel This Change"
      disabled={disabled}
      onClick={onCancel}
      size="icon-xs"
      title="Cancel This Change"
      type="button"
      variant="ghost"
    >
      <XIcon />
    </Button>
  )
}
