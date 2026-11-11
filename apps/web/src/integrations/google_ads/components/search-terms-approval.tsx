// apps/web/src/integrations/google_ads/components/search-terms-approval.tsx

import { XIcon } from "lucide-react"
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
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { formatCurrency } from "@/lib/format"
import { cn } from "@/lib/utils"
import { AttentionLine } from "@/integrations/ads/components/attention-line"
import { ChangeBanner } from "@/integrations/ads/components/change-banner"
import { ChangeSummary, type ChangeSummaryLine } from "@/integrations/ads/components/change-summary"
import { ParentTable } from "@/integrations/ads/components/parent-table"
import type { KeywordMatchType } from "@/integrations/ads/lib/keyword-notation"
import { CheckChanges } from "@/integrations/google_ads/components/check-changes"
import { SearchTermTargetCombobox } from "@/integrations/google_ads/components/search-term-target-combobox"
import { MATCH_TYPE_LABELS, MATCH_TYPES } from "@/integrations/google_ads/lib/negative-keywords"
import {
  ACTION_LABELS,
  accountCurrency,
  bulkNegativeTargets,
  cancelDecisions,
  dateRangeText,
  needsCheck,
  parseCancelled,
  restoreDecisions,
  searchTermCounts,
  searchTermParents,
  searchTermRows,
  setDecisionAction,
  setDecisionMatchType,
  setDecisionTarget,
  targetOptions,
  termStatusText,
  type OptimiseSearchTermsArgs,
  type SearchTermAction,
  type SearchTermEdit,
  type SearchTermRow,
  type TargetOption,
} from "@/integrations/google_ads/lib/search-terms"

// Below this many changes the summary and the table tools only add noise.
const TOOLS_FROM = 10
const ACTIONS: readonly SearchTermAction[] = ["add_negative", "add_keyword"]

export function SearchTermsApproval({
  args,
  checked,
  controls,
  disabled,
  onFieldEdit,
}: {
  args: OptimiseSearchTermsArgs
  // The request Google last answered for.
  checked: OptimiseSearchTermsArgs
  controls: ToolApprovalDecisionControls
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const [tab, setTab] = useState("all")
  const cancelled = useMemo(() => parseCancelled(controls.retained), [controls.retained])
  const rows = useMemo(() => searchTermRows(args, checked, cancelled), [args, checked, cancelled])
  const counts = searchTermCounts(rows)
  const currency = accountCurrency(checked)
  const [adGroup, setAdGroup] = useState<string | null>(null)
  const accountCount = new Set(rows.map((row) => row.customerId)).size
  const parents = useMemo(
    () => searchTermParents(rows, checked.accounts, accountCount > 1),
    [accountCount, checked.accounts, rows]
  )
  const grouped = parents.length > 1
  const shown = adGroup === null ? rows : rows.filter((row) => row.adGroupKey === adGroup)

  // A decision that leaves the request stays beside it, so Undo can restore it.
  const save = (edit: SearchTermEdit, restored: readonly Record<string, unknown>[] = []) => {
    const live = new Set(edit.decisions.map((value) => JSON.stringify(value)))
    controls.onRetain?.({
      decisions: [
        ...cancelled.filter((value) => !restored.includes(value)),
        ...edit.dropped,
      ].filter((value) => !live.has(JSON.stringify(value))),
    })
    onFieldEdit("decisions", edit.decisions)
  }
  const editing: RowEditing = {
    args,
    disabled,
    onAction: (ids, action) => {
      save(setDecisionAction(args, new Set(ids), action))
    },
    onCancel: (ids) => {
      save(cancelDecisions(args, new Set(ids)))
    },
    onMatchType: (ids, matchType) => {
      save(setDecisionMatchType(args, new Set(ids), matchType))
    },
    onTarget: (ids, target) => {
      save(setDecisionTarget(args, new Set(ids), target))
    },
    onUndo: (row) => {
      save(restoreDecisions(args, [row.value]), [row.value])
    },
  }
  const line = (
    id: string,
    label: string,
    count: number,
    extra: Partial<ChangeSummaryLine> = {}
  ): ChangeSummaryLine => ({
    count,
    id,
    label,
    onSelect: () => {
      setAdGroup(null)
      setTab(id)
    },
    selected: tab === id,
    ...extra,
  })
  const blocked = rows.filter((row) => row.problem !== null && !row.cancelled)
  const money = (value: number) => formatCurrency(value, currency)

  return (
    <div className="grid min-w-0 gap-3">
      <ChangeBanner
        aside={
          counts.blockedCost > 0 ? (
            <div className="text-right">
              <p className="text-sm font-medium tabular-nums">{money(counts.blockedCost)}</p>
              <p className="text-muted-foreground text-xs">spent on terms being blocked</p>
            </div>
          ) : undefined
        }
        detail={[
          countText(counts.negatives, "negative", "negatives"),
          countText(counts.keywords, "keyword", "keywords"),
          `figures from Google, ${dateRangeText(checked)}`,
        ]
          .filter(Boolean)
          .join(" · ")}
      />
      {rows.length >= TOOLS_FROM ? (
        <>
          <ChangeSummary
            lines={[
              line("add_negative", "Block as Negatives", counts.negatives, {
                detail: `${money(counts.blockedCost)} spent`,
              }),
              line("add_keyword", "Add as Keywords", counts.keywords),
              line("already_set", "Already Set", counts.alreadySet, {
                detail: "already a keyword or negative there, skipped",
              }),
              line("attention", "Needs Attention", counts.problems, {
                tone: "danger",
                action: (
                  <Button
                    disabled={disabled}
                    onClick={() => {
                      editing.onCancel(blocked.map((row) => row.id))
                    }}
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    Cancel These {String(counts.problems)}
                  </Button>
                ),
              }),
            ]}
          />
          <AttentionLine
            count={counts.problems}
            onShow={() => {
              setAdGroup(null)
              setTab("attention")
            }}
          />
        </>
      ) : null}
      {grouped ? (
        <ParentTable
          columns={parentColumns(currency)}
          disabled={disabled}
          label="Ad Groups"
          onCancel={(key) => {
            editing.onCancel(
              rows.filter((row) => row.adGroupKey === key && !row.cancelled).map((row) => row.id)
            )
          }}
          onSelect={setAdGroup}
          onUndo={(key) => {
            const values = rows
              .filter((row) => row.adGroupKey === key && row.cancelled)
              .map((row) => row.value)
            save(restoreDecisions(args, values), values)
          }}
          rowNoun={["ad group", "ad groups"]}
          rows={parents}
          selected={adGroup}
        />
      ) : null}
      <ChangeTable
        currency={currency}
        editing={editing}
        grouped={grouped}
        onTabChange={setTab}
        rows={shown}
        tab={tab}
      />
      {needsCheck(args, checked) && args.decisions.length > 0 ? (
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

type RowEditing = {
  args: OptimiseSearchTermsArgs
  disabled: boolean
  onAction: (ids: Iterable<string>, action: SearchTermAction) => void
  onCancel: (ids: Iterable<string>) => void
  onMatchType: (ids: Iterable<string>, matchType: KeywordMatchType) => void
  onTarget: (ids: Iterable<string>, target: TargetOption) => void
  onUndo: (row: SearchTermRow) => void
}

function countText(count: number, one: string, many: string): string | null {
  return count > 0 ? `${count.toLocaleString("en-GB")} ${count === 1 ? one : many}` : null
}

function costColumn(currency: string | null): DataColumn {
  return {
    key: "cost",
    kind: "currency",
    label: "Cost",
    align: "right",
    isMetric: true,
    unit: "currency-units",
    width: 96,
    ...(currency ? { currencyCode: currency } : {}),
  }
}

function parentColumns(currency: string | null): DataColumn[] {
  return [
    { key: "campaign", kind: "text", label: "Campaign", width: 200 },
    { key: "terms", kind: "number", label: "Terms", width: 80 },
    costColumn(currency),
    { key: "problems", kind: "text", label: "Problems", width: 110 },
  ]
}

function columns(currency: string | null): DataColumn[] {
  return [
    { key: "term", kind: "text", label: "Search Term", width: 240 },
    // Shown under each term; kept as a column for search and the CSV.
    { key: "matched", kind: "text", label: "Matched In", hidden: true },
    { key: "clicks", kind: "number", label: "Clicks", align: "right", isMetric: true, width: 72 },
    costColumn(currency),
    {
      key: "conversions",
      kind: "number",
      label: "Conv.",
      align: "right",
      isMetric: true,
      width: 64,
    },
    { key: "action", kind: "text", label: "Action", width: 148 },
    { key: "match", kind: "text", label: "Match Type", width: 116 },
    { key: "target", kind: "text", label: "Target", width: 232 },
    { key: "cancel", kind: "text", label: "Cancel", width: 64 },
  ]
}

function ChangeTable({
  currency,
  editing,
  grouped,
  onTabChange,
  rows,
  tab,
}: {
  currency: string | null
  editing: RowEditing
  // The ad groups table above names where each term matched.
  grouped: boolean
  onTabChange: (id: string) => void
  rows: readonly SearchTermRow[]
  tab: string
}) {
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set())
  const byId = useMemo(() => new Map(rows.map((row) => [row.id, row])), [rows])
  const tabs = useMemo(() => searchTermTabs(byId), [byId])
  const tableColumns = useMemo(() => columns(currency), [currency])
  const tools = rows.length >= TOOLS_FROM
  const { disabled } = editing
  const chosen = [...selected].flatMap((id) => byId.get(id) ?? [])
  const bulkTargets = bulkNegativeTargets(editing.args, chosen)
  const bulkCustomer = chosen[0]?.customerId
  const bulk = (run: () => void) => () => {
    run()
    setSelected(new Set())
  }
  return (
    <DataTable
      activeTab={tab}
      columns={tableColumns}
      exportFilename="google-ads-search-terms.csv"
      onTabChange={onTabChange}
      pageSize={25}
      renderCell={(column, row) => {
        const change = byId.get(String(row["key"]))
        if (!change) return null
        if (column.key === "term") return <TermCell grouped={grouped} row={change} />
        if (column.key === "action")
          return (
            <ChoiceCell
              disabled={disabled || change.cancelled}
              label={`Action for ${change.term}`}
              onChange={(action) => {
                editing.onAction([change.id], action as SearchTermAction)
              }}
              options={ACTIONS.map((action) => ({ label: ACTION_LABELS[action], value: action }))}
              value={change.action}
            />
          )
        if (column.key === "match")
          return (
            <ChoiceCell
              disabled={disabled || change.cancelled}
              label={`Match type for ${change.term}`}
              onChange={(matchType) => {
                editing.onMatchType([change.id], matchType as KeywordMatchType)
              }}
              options={MATCH_TYPES.map((matchType) => ({
                label: MATCH_TYPE_LABELS[matchType],
                value: matchType,
              }))}
              value={change.matchType}
            />
          )
        if (column.key === "target") return <TargetCell editing={editing} row={change} />
        if (column.key === "cancel") return <CancelCell editing={editing} row={change} />
        return null
      }}
      rowClassName={(row) => (byId.get(String(row["key"]))?.cancelled ? "opacity-60" : undefined)}
      rowDetails={false}
      rowNoun={["search term", "search terms"]}
      rows={rows.map(tableRow)}
      {...(tools
        ? {
            searchable: true,
            selection: {
              actions: (
                <>
                  {ACTIONS.map((action) => (
                    <Button
                      key={action}
                      disabled={disabled}
                      onClick={bulk(() => {
                        editing.onAction(selected, action)
                      })}
                      size="sm"
                      type="button"
                      variant="outline"
                    >
                      {action === "add_negative" ? "Set to Block" : "Set to Add Keyword"}
                    </Button>
                  ))}
                  {MATCH_TYPES.map((matchType) => (
                    <Button
                      key={matchType}
                      disabled={disabled}
                      onClick={bulk(() => {
                        editing.onMatchType(selected, matchType)
                      })}
                      size="sm"
                      type="button"
                      variant="outline"
                    >
                      Set to {MATCH_TYPE_LABELS[matchType]}
                    </Button>
                  ))}
                  {bulkTargets.length > 0 && bulkCustomer ? (
                    <SearchTermTargetCombobox
                      className="h-7 min-h-7 w-56 pr-1"
                      customerId={bulkCustomer}
                      disabled={disabled}
                      label="Block the selected terms in"
                      onChoose={(target) => {
                        bulk(() => {
                          editing.onTarget(selected, target)
                        })()
                      }}
                      options={bulkTargets}
                      placeholder="Block In…"
                      searchKind="list"
                      value={null}
                    />
                  ) : null}
                  <Button
                    disabled={disabled}
                    onClick={bulk(() => {
                      editing.onCancel(selected)
                    })}
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    Cancel These Changes
                  </Button>
                </>
              ),
              onChange: setSelected,
              rowId: (row) => String(row["key"]),
              selected,
            },
            tabs,
          }
        : {})}
    />
  )
}

function tableRow(row: SearchTermRow): DataRow {
  return {
    action: ACTION_LABELS[row.action],
    cancel: "",
    clicks: row.clicks,
    conversions: row.conversions,
    cost: row.cost,
    key: row.id,
    match: MATCH_TYPE_LABELS[row.matchType],
    matched: `${row.campaignName} › ${row.adGroupName}`,
    target: row.targetName,
    term: row.term,
  }
}

function searchTermTabs(byId: ReadonlyMap<string, SearchTermRow>): DataTableTab[] {
  const live = (row: DataRow, match: (change: SearchTermRow) => boolean) => {
    const change = byId.get(String(row["key"]))
    return change !== undefined && !change.cancelled && match(change)
  }
  return [
    { id: "all", label: "All", match: () => true },
    {
      hideWhenEmpty: true,
      id: "add_negative",
      label: "Block",
      match: (row) => live(row, (change) => change.action === "add_negative"),
    },
    {
      hideWhenEmpty: true,
      id: "add_keyword",
      label: "Add Keyword",
      match: (row) => live(row, (change) => change.action === "add_keyword"),
    },
    {
      hideWhenEmpty: true,
      id: "already_set",
      label: "Already Set",
      match: (row) => live(row, (change) => change.state === "already_set"),
    },
    {
      hideWhenEmpty: true,
      id: "attention",
      label: "Needs Attention",
      match: (row) => live(row, (change) => change.problem !== null),
    },
  ]
}

function TermCell({ grouped, row }: { grouped: boolean; row: SearchTermRow }) {
  return (
    <div className="grid min-w-0 gap-0.5 text-sm whitespace-normal">
      <span className={cn("font-medium wrap-anywhere", row.cancelled && "line-through")}>
        {row.term}
      </span>
      {grouped ? null : (
        <span className="text-muted-foreground text-xs wrap-anywhere">
          {row.campaignName} › {row.adGroupName}
        </span>
      )}
      {!row.cancelled && row.state !== "already_set" && termStatusText(row.termStatus) ? (
        <span className="text-muted-foreground text-xs">{termStatusText(row.termStatus)}</span>
      ) : null}
      {!row.cancelled && row.state === "already_set" ? (
        <Badge className="w-fit" variant="secondary">
          Already Set, skipped
        </Badge>
      ) : null}
      {!row.cancelled && row.problem ? (
        <span className="text-destructive text-xs wrap-anywhere">{row.problem}</span>
      ) : null}
    </div>
  )
}

function ChoiceCell({
  disabled,
  label,
  onChange,
  options,
  value,
}: {
  disabled: boolean
  label: string
  onChange: (value: string) => void
  options: readonly { label: string; value: string }[]
  value: string
}) {
  const current = options.find((option) => option.value === value)
  if (disabled || options.length < 2)
    return (
      <span className="text-sm wrap-anywhere whitespace-normal">{current?.label ?? value}</span>
    )
  return (
    <Select<string>
      onValueChange={(next) => {
        if (next !== null && next !== value) onChange(next)
      }}
      value={value}
    >
      {/* Full width with the value truncated, since table cells clip what overflows. */}
      <SelectTrigger aria-label={label} className="w-full min-w-0" size="sm">
        <SelectValue className="min-w-0 truncate">{current?.label}</SelectValue>
      </SelectTrigger>
      <SelectContent align="start" alignItemWithTrigger={false} className="w-auto">
        <SelectGroup>
          {options.map((option) => (
            <SelectItem key={option.value} label={option.label} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}

function TargetCell({ editing, row }: { editing: RowEditing; row: SearchTermRow }) {
  const options = targetOptions(editing.args, row)
  if (editing.disabled || row.cancelled)
    return <span className="text-sm wrap-anywhere whitespace-normal">{row.targetName}</span>
  const current = options.find((option) => option.value === row.target) ?? {
    detail: "",
    label: row.targetName,
    value: row.target,
  }
  return (
    <SearchTermTargetCombobox
      customerId={row.customerId}
      disabled={editing.disabled}
      label={`Target for ${row.term}`}
      onChoose={(target) => {
        editing.onTarget([row.id], target)
      }}
      options={options}
      placeholder="Choose a target"
      searchKind={row.action === "add_negative" ? "list" : "ad_group"}
      value={current}
    />
  )
}

function CancelCell({ editing, row }: { editing: RowEditing; row: SearchTermRow }) {
  const { disabled } = editing
  return row.cancelled ? (
    <Button
      disabled={disabled}
      onClick={() => {
        editing.onUndo(row)
      }}
      size="sm"
      type="button"
      variant="ghost"
    >
      Undo
    </Button>
  ) : (
    <Button
      aria-label="Cancel This Change"
      disabled={disabled}
      onClick={() => {
        editing.onCancel([row.id])
      }}
      size="icon-xs"
      title="Cancel This Change"
      type="button"
      variant="ghost"
    >
      <XIcon />
    </Button>
  )
}
