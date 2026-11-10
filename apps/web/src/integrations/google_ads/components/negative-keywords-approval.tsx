// apps/web/src/integrations/google_ads/components/negative-keywords-approval.tsx

import { PlusIcon, XIcon } from "lucide-react"
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
import { cn } from "@/lib/utils"
import { AttentionLine } from "@/integrations/ads/components/attention-line"
import { ChangeBanner } from "@/integrations/ads/components/change-banner"
import { ChangeSummary, type ChangeSummaryLine } from "@/integrations/ads/components/change-summary"
import { EntityPicker } from "@/integrations/ads/components/entity-picker"
import { KeywordPaste } from "@/integrations/ads/components/keyword-paste"
import type { KeywordMatchType, PastedKeyword } from "@/integrations/ads/lib/keyword-notation"
import { CheckChanges } from "@/integrations/google_ads/components/check-changes"
import { NegativeTargetCombobox } from "@/integrations/google_ads/components/negative-target-combobox"
import {
  addKeywords,
  addListCampaign,
  cancelRows,
  MATCH_TYPE_LABELS,
  MATCH_TYPES,
  needsCheck,
  negativeCounts,
  negativeRows,
  parseCancelled,
  restoreRow,
  serializeCancelled,
  serializeEntries,
  setMatchType,
  TARGET_KIND_LABELS,
  targetsText,
  type NegativeEntry,
  type NegativeRow,
  type UpdateNegativeKeywordsArgs,
} from "@/integrations/google_ads/lib/negative-keywords"

const TOOL = "google_ads_update_negative_keywords"
// Below this many changes the summary and the table tools only add noise.
const TOOLS_FROM = 10

const COLUMNS: DataColumn[] = [
  { key: "name", kind: "text", label: "Negative Keyword", width: 220 },
  { key: "match", kind: "text", label: "Match Type", width: 120 },
  { key: "target", kind: "text", label: "Target", width: 220 },
  { key: "cancel", kind: "text", label: "Cancel", width: 70 },
]

type Action = NegativeRow["action"]

const SECTIONS: readonly { action: Action; title: string; detail: string; target: string }[] = [
  {
    action: "add",
    title: "Add Negative Keywords",
    detail: "Ads stop showing for these searches.",
    target: "Added To",
  },
  {
    action: "remove",
    title: "Remove Negative Keywords",
    detail: "Ads can show for these searches again.",
    target: "Removed From",
  },
]

export function NegativeKeywordsApproval({
  args,
  checked,
  controls,
  disabled,
  onFieldEdit,
}: {
  args: UpdateNegativeKeywordsArgs
  // The request Google last answered for.
  checked: UpdateNegativeKeywordsArgs
  controls: ToolApprovalDecisionControls
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const [tabs, setTabs] = useState<Record<Action, string>>({ add: "all", remove: "all" })
  const [adding, setAdding] = useState(false)
  const cancelled = useMemo(() => parseCancelled(controls.retained), [controls.retained])
  const rows = useMemo(
    () => negativeRows(args, checked, cancelled.rows),
    [args, checked, cancelled.rows]
  )
  const counts = negativeCounts(rows)

  // A row or target that leaves the request stays beside it, so Undo can restore it.
  const save = (next: readonly NegativeEntry[], dropped: readonly NegativeRow[] = []) => {
    const kept = new Set(next.map((entry) => entry.key))
    const live = new Set(
      negativeRows({ ...args, entries: [...next] }, checked).map((row) => row.id)
    )
    controls.onRetain?.(
      serializeCancelled({
        entries: [
          ...cancelled.entries.filter((entry) => !kept.has(entry.key)),
          ...args.entries.filter((entry) => !kept.has(entry.key)),
        ],
        rows: [...cancelled.rows, ...dropped].filter((row) => !live.has(row.id)),
      })
    )
    onFieldEdit("entries", serializeEntries(next))
  }
  const editing: ChangeEditing = {
    disabled,
    onCancel: (ids) => {
      const edit = cancelRows(args, rows, new Set(ids))
      save(edit.entries, edit.dropped)
    },
    onMatchType: (ids, matchType) => {
      const edit = setMatchType(args, rows, new Set(ids), matchType)
      save(edit.entries, edit.dropped)
    },
    onUndo: (row) => {
      save(restoreRow(args, cancelled.entries, row))
    },
  }
  // A summary line filters whichever tables hold its rows.
  const show = (id: string, match: (row: NegativeRow) => boolean) => {
    const has = (action: Action) =>
      rows.some((row) => row.action === action && !row.cancelled && match(row))
    setTabs({ add: has("add") ? id : "all", remove: has("remove") ? id : "all" })
  }
  const lineFor = (
    id: string,
    label: string,
    count: number,
    match: (row: NegativeRow) => boolean,
    extra: Partial<ChangeSummaryLine> = {}
  ): ChangeSummaryLine => ({
    count,
    id,
    label,
    onSelect: () => {
      show(id, match)
    },
    selected: tabs.add === id || tabs.remove === id,
    ...extra,
  })
  const hasProblem = (row: NegativeRow) => row.problem !== null
  const blocked = rows.filter((row) => hasProblem(row) && !row.cancelled)

  return (
    <div className="grid min-w-0 gap-3">
      <ChangeBanner
        aside={
          counts.add > 0 ? (
            <p className="text-sm font-medium tabular-nums">
              {counts.add.toLocaleString("en-GB")} {counts.add === 1 ? "search" : "searches"}{" "}
              blocked
            </p>
          ) : undefined
        }
        detail={[
          countText(counts.total - counts.remove, "to add"),
          countText(counts.remove, "to remove"),
          targetsText(args) || "nothing left",
        ]
          .filter(Boolean)
          .join(" · ")}
      />
      {rows.length >= TOOLS_FROM ? (
        <>
          <ChangeSummary
            lines={[
              lineFor(
                "already_set",
                "Already in Place",
                counts.alreadySet,
                (row) => row.state === "already_set",
                { detail: "skipped, nothing changes" }
              ),
              lineFor(
                "not_found",
                "Not There to Remove",
                counts.notFound,
                (row) => row.state === "not_found",
                { detail: "skipped, nothing changes" }
              ),
              lineFor("attention", "Needs Attention", counts.problems, hasProblem, {
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
              show("attention", hasProblem)
            }}
          />
        </>
      ) : null}
      {rows.length === 1 && rows[0] ? (
        <SingleChange editing={editing} row={rows[0]} />
      ) : (
        SECTIONS.map((section) => {
          const sectionRows = rows.filter((row) => row.action === section.action)
          if (sectionRows.length === 0) return null
          const live = sectionRows.filter((row) => !row.cancelled).length
          return (
            <section key={section.action} aria-label={section.title} className="grid gap-2">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <h3 className="text-sm font-medium">
                  {section.title}{" "}
                  <span className="text-muted-foreground tabular-nums">
                    {live.toLocaleString("en-GB")}
                  </span>
                </h3>
                <p className="text-muted-foreground text-sm">{section.detail}</p>
              </div>
              <ChangeTable
                editing={editing}
                onTabChange={(id) => {
                  setTabs((current) => ({ ...current, [section.action]: id }))
                }}
                rows={sectionRows}
                tab={tabs[section.action]}
                targetLabel={section.target}
              />
            </section>
          )
        })
      )}
      {adding && args.entries.length > 0 ? (
        <AddPanel
          args={args}
          disabled={disabled}
          onAdd={(targets, keywords) => {
            save(addKeywords(args, targets, keywords))
            setAdding(false)
          }}
          onCampaign={(targetKey, value) => {
            save(addListCampaign(args, targetKey, value))
          }}
          onDone={() => {
            setAdding(false)
          }}
        />
      ) : args.entries.length > 0 ? (
        <Button
          className="w-fit"
          disabled={disabled}
          onClick={() => {
            setAdding(true)
          }}
          type="button"
          variant="ghost"
        >
          <PlusIcon aria-hidden="true" />
          Add Negative Keywords
        </Button>
      ) : null}
      {needsCheck(args, checked) && args.entries.length > 0 ? (
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

type ChangeEditing = {
  disabled: boolean
  onCancel: (ids: Iterable<string>) => void
  onMatchType: (ids: Iterable<string>, matchType: KeywordMatchType) => void
  onUndo: (row: NegativeRow) => void
}

function countText(count: number, label: string): string | null {
  return count > 0 ? `${count.toLocaleString("en-GB")} ${label}` : null
}

/** The adds or the removes, with their own filters and bulk bar. */
function ChangeTable({
  editing,
  onTabChange,
  rows,
  tab,
  targetLabel,
}: {
  editing: ChangeEditing
  onTabChange: (id: string) => void
  rows: readonly NegativeRow[]
  tab: string
  targetLabel: string
}) {
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set())
  const byId = useMemo(() => new Map(rows.map((row) => [row.id, row])), [rows])
  const tabs = useMemo(() => negativeTabs(byId), [byId])
  const columns = useMemo(
    () =>
      COLUMNS.map((column) =>
        column.key === "target" ? { ...column, label: targetLabel } : column
      ),
    [targetLabel]
  )
  const tools = rows.length >= TOOLS_FROM
  const { disabled } = editing
  const bulk = (run: () => void) => () => {
    run()
    setSelected(new Set())
  }
  return (
    <DataTable
      activeTab={tab}
      columns={columns}
      exportFilename="google-ads-negative-keywords.csv"
      onTabChange={onTabChange}
      pageSize={10}
      renderCell={(column, row) => {
        const change = byId.get(String(row["key"]))
        if (!change) return null
        if (column.key === "name") return <NameCell row={change} />
        if (column.key === "match")
          return (
            <MatchTypeCell
              disabled={disabled}
              onChange={(matchType) => {
                editing.onMatchType([change.id], matchType)
              }}
              row={change}
            />
          )
        if (column.key === "target")
          return (
            <span className="text-sm wrap-anywhere whitespace-normal">{String(row["target"])}</span>
          )
        if (column.key === "cancel") return <CancelCell editing={editing} row={change} />
        return null
      }}
      rowClassName={(row) => (byId.get(String(row["key"]))?.cancelled ? "opacity-60" : undefined)}
      rowDetails={false}
      rowNoun={["change", "changes"]}
      rows={rows.map((row) => tableRow(row))}
      {...(tools
        ? {
            searchable: true,
            selection: {
              actions: (
                <>
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

function tableRow(row: NegativeRow): DataRow {
  return {
    cancel: "",
    key: row.id,
    match: row.matchType ? MATCH_TYPE_LABELS[row.matchType] : "",
    name: row.name,
    target: `${row.targetName} · ${TARGET_KIND_LABELS[row.targetKind]}`,
  }
}

function negativeTabs(byId: ReadonlyMap<string, NegativeRow>): DataTableTab[] {
  const live = (row: DataRow, match: (change: NegativeRow) => boolean) => {
    const change = byId.get(String(row["key"]))
    return change !== undefined && !change.cancelled && match(change)
  }
  const targets = new Map([...byId.values()].map((row) => [row.targetKey, row.targetName]))
  return [
    { id: "all", label: "All", match: () => true },
    ...(targets.size > 1
      ? [...targets].map(([key, name]) => ({
          hideWhenEmpty: true,
          id: `target:${key}`,
          label: name,
          match: (row: DataRow) => live(row, (change) => change.targetKey === key),
        }))
      : []),
    {
      hideWhenEmpty: true,
      id: "already_set",
      label: "Already in Place",
      match: (row) => live(row, (change) => change.state === "already_set"),
    },
    {
      hideWhenEmpty: true,
      id: "not_found",
      label: "Not There",
      match: (row) => live(row, (change) => change.state === "not_found"),
    },
    {
      hideWhenEmpty: true,
      id: "attention",
      label: "Needs Attention",
      match: (row) => live(row, (change) => change.problem !== null),
    },
  ]
}

function NameCell({ row }: { row: NegativeRow }) {
  return (
    <div className="grid min-w-0 gap-0.5 text-sm whitespace-normal">
      <span className={cn("font-medium wrap-anywhere", row.cancelled && "line-through")}>
        {row.name}
      </span>
      {row.item === "campaign" ? (
        <span className="text-muted-foreground text-xs">
          {row.action === "add"
            ? "Campaign starts using this list"
            : "Campaign stops using this list"}
        </span>
      ) : null}
      {!row.cancelled && row.state !== "change" && row.state !== "unchecked" ? (
        <Badge className="w-fit" variant="secondary">
          {row.state === "already_set" ? "Already in Place, skipped" : "Not There, skipped"}
        </Badge>
      ) : null}
      {!row.cancelled && row.problem ? (
        <span className="text-destructive text-xs wrap-anywhere">{row.problem}</span>
      ) : null}
    </div>
  )
}

function MatchTypeCell({
  disabled,
  onChange,
  row,
}: {
  disabled: boolean
  onChange: (matchType: KeywordMatchType) => void
  row: NegativeRow
}) {
  if (row.matchType === null) return null
  if (row.cancelled) return <span className="text-sm">{MATCH_TYPE_LABELS[row.matchType]}</span>
  return (
    <Select<KeywordMatchType>
      disabled={disabled}
      onValueChange={(next) => {
        if (next !== null) onChange(next)
      }}
      value={row.matchType}
    >
      <SelectTrigger aria-label={`Match type for ${row.name}`} size="sm">
        <SelectValue />
      </SelectTrigger>
      <SelectContent align="start">
        <SelectGroup>
          {MATCH_TYPES.map((matchType) => (
            <SelectItem key={matchType} label={MATCH_TYPE_LABELS[matchType]} value={matchType}>
              {MATCH_TYPE_LABELS[matchType]}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}

function changeLabel(row: NegativeRow): string {
  if (row.item === "campaign") return row.action === "add" ? "Use List" : "Stop Using List"
  return row.action === "add" ? "Add" : "Remove"
}

function ChangeCell({ row }: { row: NegativeRow }) {
  if (row.cancelled) return <span className="text-sm line-through">{changeLabel(row)}</span>
  if (row.state === "already_set") return <Badge variant="secondary">Already in Place</Badge>
  if (row.state === "not_found") return <Badge variant="secondary">Not There</Badge>
  return <Badge variant={row.action === "add" ? "success" : "warning"}>{changeLabel(row)}</Badge>
}

function CancelCell({ editing, row }: { editing: ChangeEditing; row: NegativeRow }) {
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

/** One change on its own reads as a sentence, not a table. */
function SingleChange({ editing, row }: { editing: ChangeEditing; row: NegativeRow }) {
  const verb =
    row.item === "campaign"
      ? row.action === "add"
        ? "Use the list in"
        : "Stop using the list in"
      : row.action === "add"
        ? "Block searches for"
        : "Stop blocking searches for"
  return (
    <div className="grid gap-2 rounded-lg border px-3 py-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className={row.cancelled ? "line-through" : undefined}>
          {verb} <span className="font-medium">{row.name}</span>
          {row.item === "keyword" ? ` in ${row.targetName}` : ""}
        </span>
        {row.item === "keyword" ? (
          <MatchTypeCell
            disabled={editing.disabled}
            onChange={(matchType) => {
              editing.onMatchType([row.id], matchType)
            }}
            row={row}
          />
        ) : null}
        <ChangeCell row={row} />
        <span className="ml-auto">
          <CancelCell editing={editing} row={row} />
        </span>
      </div>
      {!row.cancelled && row.problem ? (
        <p className="text-destructive text-sm wrap-anywhere">{row.problem}</p>
      ) : null}
    </div>
  )
}

function AddPanel({
  args,
  disabled,
  onAdd,
  onCampaign,
  onDone,
}: {
  args: UpdateNegativeKeywordsArgs
  disabled: boolean
  onAdd: (targets: readonly NegativeEntry[], keywords: PastedKeyword[]) => void
  onCampaign: (targetKey: string, value: Record<string, unknown>) => void
  onDone: () => void
}) {
  const [keywords, setKeywords] = useState<PastedKeyword[]>([])
  const [targets, setTargets] = useState<readonly NegativeEntry[]>(() => args.entries)
  const chosen = new Set(targets.map((target) => target.key))
  const unchosen = args.entries.filter((entry) => !chosen.has(entry.key))
  const lists = args.entries.filter((entry) => entry.kind === "list" || entry.kind === "new_list")
  return (
    <section aria-label="Add negative keywords" className="bg-muted/40 grid gap-4 rounded-lg p-3">
      <div className="grid gap-1.5">
        <p className="text-sm font-medium">Add To</p>
        <NegativeTargetCombobox
          disabled={disabled}
          onChange={setTargets}
          targets={targets}
          toolName={TOOL}
        />
        {unchosen.length > 0 ? (
          <div className="text-muted-foreground flex flex-wrap items-center gap-x-1 text-xs">
            <span>In this request:</span>
            {unchosen.map((entry) => (
              <button
                key={entry.key}
                className="text-foreground hover:bg-muted rounded px-1 py-0.5 underline-offset-2 hover:underline disabled:opacity-50"
                disabled={disabled}
                onClick={() => {
                  setTargets([...targets, entry])
                }}
                type="button"
              >
                + {entry.label}
              </button>
            ))}
          </div>
        ) : null}
      </div>
      <KeywordPaste
        disabled={disabled}
        keywords={keywords}
        label="Negative Keywords"
        onChange={setKeywords}
      />
      {lists.map((entry) => (
        <EntityPicker
          key={entry.key}
          currentLabel={null}
          disabled={disabled}
          entityKind="google_ads_campaign"
          fieldKey="entries"
          label={`Campaign to Use ${targetsText({ ...args, entries: [entry] })}`}
          onChoose={(value) => {
            onCampaign(entry.key, value)
          }}
          toolName={TOOL}
        />
      ))}
      <div className="flex flex-wrap gap-2">
        <Button
          disabled={disabled || keywords.length === 0 || targets.length === 0}
          onClick={() => {
            onAdd(targets, keywords)
          }}
          type="button"
        >
          {keywords.length > 0
            ? `Add ${String(keywords.length)} Negative ${keywords.length === 1 ? "Keyword" : "Keywords"}`
            : "Add Negative Keywords"}
        </Button>
        <Button disabled={disabled} onClick={onDone} type="button" variant="ghost">
          Done
        </Button>
      </div>
    </section>
  )
}
