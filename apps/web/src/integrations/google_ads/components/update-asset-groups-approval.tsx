// apps/web/src/integrations/google_ads/components/update-asset-groups-approval.tsx

import { PlusIcon } from "lucide-react"
import { useMemo, useState, type ReactNode } from "react"

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
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { CancelCell } from "@/integrations/ads/components/cancel-cell"
import { ChangeBanner } from "@/integrations/ads/components/change-banner"
import { CommittedInput } from "@/integrations/ads/components/committed-input"
import { EntitySearch } from "@/integrations/ads/components/entity-search"
import { ParentTable } from "@/integrations/ads/components/parent-table"
import { cellText } from "@/integrations/ads/lib/cell-text"
import {
  parseCancelled,
  restoreParent,
  restoreRow,
  retainCancelled,
  serializeCancelled,
} from "@/integrations/ads/lib/cancelled-rows"
import { CheckChanges } from "@/integrations/google_ads/components/check-changes"
import { ProblemList } from "@/integrations/google_ads/components/new-ad-groups"
import { characterCount } from "@/integrations/google_ads/lib/create-ads"
import {
  addGroupItem,
  canCheckGroups,
  cancelGroupChanges,
  editGroupChange,
  GROUP_CANCEL_CARD,
  GROUP_CHANGE_LABELS,
  groupChangeRows,
  groupCheckIncomplete,
  groupCounts,
  groupLimitProblems,
  groupParents,
  groupsNeedCheck,
  IMAGE_KINDS,
  ITEM_KINDS,
  kindSummary,
  limitProblem,
  serializeEntries,
  TEXT_KINDS,
  TEXT_LIMITS,
  type GroupChangeRow,
  type GroupEntry,
  type ItemKind,
  type KindSummary,
  type UpdateAssetGroupsArgs,
} from "@/integrations/google_ads/lib/update-asset-groups"
import { isRecord } from "@/lib/guards"
import { cn } from "@/lib/utils"

const TOOL = "google_ads_update_asset_groups"
const FIELD = "entries"
// Below this many changes the table tools only add noise.
const TOOLS_FROM = 10
const ALL = "all"

const PARENT_COLUMNS: DataColumn[] = [
  { key: "now", kind: "text", label: "Assets Now", width: 280 },
  { key: "changes", kind: "number", label: "Changes", width: 90 },
  { key: "problems", kind: "text", label: "Problems", width: 110 },
]

const SUMMARY_COLUMNS: DataColumn[] = [
  { key: "type", kind: "text", label: "Asset Type", width: 180 },
  { key: "now", kind: "number", label: "Now", width: 70 },
  { key: "removing", kind: "number", label: "Removing", width: 90 },
  { key: "adding", kind: "number", label: "Adding", width: 80 },
  { key: "after", kind: "number", label: "After", width: 70 },
  { key: "allowed", kind: "text", label: "Google Allows", width: 120 },
  { key: "status", kind: "text", label: "Status", width: 200 },
]

const SETTING_COLUMNS: DataColumn[] = [
  { key: "setting", kind: "text", label: "Setting", width: 120 },
  { key: "now", kind: "text", label: "Now", width: 240 },
  { key: "value", kind: "text", label: "New", width: 320 },
  { key: "cancel", kind: "text", label: "Cancel", width: 70 },
]

const REMOVAL_COLUMNS: DataColumn[] = [
  { key: "asset", kind: "text", label: "Asset", width: 420 },
  { key: "type", kind: "text", label: "Type", width: 150 },
  { key: "cancel", kind: "text", label: "Cancel", width: 70 },
]

const ADDITION_COLUMNS: DataColumn[] = [
  { key: "asset", kind: "text", label: "Asset", width: 420 },
  { key: "type", kind: "text", label: "Type", width: 150 },
  { key: "length", kind: "text", label: "Length", width: 80 },
  { key: "cancel", kind: "text", label: "Cancel", width: 70 },
]

const AUDIENCE_KINDS: readonly unknown[] = ["user_list", "user_interest", "custom_audience"]

type Left = { entries: readonly GroupEntry[]; rows: readonly GroupChangeRow[] }
const NOTHING_LEFT: Left = { entries: [], rows: [] }

export function UpdateAssetGroupsApproval({
  args,
  checked,
  controls,
  disabled,
  onFieldEdit,
}: {
  args: UpdateAssetGroupsArgs
  // The request Google last answered for.
  checked: UpdateAssetGroupsArgs
  controls: ToolApprovalDecisionControls
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const cancelled = useMemo(
    () => parseCancelled(GROUP_CANCEL_CARD, controls.retained),
    [controls.retained]
  )
  const rows = useMemo(
    () => groupChangeRows(args, checked, cancelled.rows),
    [args, checked, cancelled.rows]
  )
  const counts = groupCounts(rows)
  const accountCount = new Set(rows.map((row) => row.targetKey.split("/")[1])).size
  const parents = useMemo(
    () => groupParents(args, rows, accountCount > 1),
    [accountCount, args, rows]
  )
  const [picked, setPicked] = useState<string | null>(null)
  const [kind, setKind] = useState<string>(ALL)
  // Counts are per asset group, so one group is always in view.
  const group = parents.find((parent) => parent.key === picked)?.key ?? parents[0]?.key ?? null
  const groupRows = rows.filter((row) => row.targetKey === group)
  const summary = group ? kindSummary(args, rows, group) : null

  // Cancelled changes stay beside the request, so Undo can restore them.
  const save = (next: GroupEntry[], left: Left = NOTHING_LEFT) => {
    const rowIds = new Set(
      groupChangeRows({ ...args, entries: next }, checked).map((row) => row.id)
    )
    controls.onRetain?.(
      serializeCancelled(
        GROUP_CANCEL_CARD,
        retainCancelled(cancelled, left, { entries: next, rowIds })
      )
    )
    onFieldEdit(FIELD, serializeEntries(next))
  }
  const cancel = (ids: Iterable<string>) => {
    const edit = cancelGroupChanges(args, rows, new Set(ids))
    save(edit.entries, { entries: edit.departed, rows: edit.dropped })
  }
  const undo = (row: GroupChangeRow) => {
    save(restoreRow(GROUP_CANCEL_CARD, args.entries, cancelled.entries, row))
  }
  const edit = (row: GroupChangeRow, next: unknown) => {
    save(editGroupChange(args, row, next))
  }
  const signals = rows.some((row) => row.kind === "search_theme" || row.kind === "audience_signal")

  return (
    <div className="grid min-w-0 gap-4">
      <ChangeBanner
        detail={[
          `${parents.length.toLocaleString("en-GB")} ${parents.length === 1 ? "asset group" : "asset groups"}`,
          signals
            ? "Search themes and audience signals guide Google; they don't limit who sees your ads"
            : null,
        ]
          .filter(Boolean)
          .join(" · ")}
      />
      <ProblemList problems={groupLimitProblems(args)} />
      {parents.length > 0 ? (
        <ParentTable
          columns={PARENT_COLUMNS}
          disabled={disabled}
          label="Asset Groups"
          onCancel={(key) => {
            cancel(
              rows.filter((row) => row.targetKey === key && !row.cancelled).map((row) => row.id)
            )
          }}
          onSelect={setPicked}
          onUndo={(key) => {
            save(restoreParent(GROUP_CANCEL_CARD, args.entries, cancelled.entries, rows, key))
          }}
          rowNoun={["asset group", "asset groups"]}
          rows={parents}
          selected={parents.length > 1 ? group : null}
        />
      ) : null}
      {group ? (
        <>
          <Settings
            disabled={disabled}
            onCancel={cancel}
            onEdit={edit}
            onUndo={undo}
            rows={groupRows.filter((row) => row.action === "set")}
          />
          {summary ? (
            <Section
              aside="Updates as you change, cancel, or add items. Click a type to filter the tables."
              title="What the Asset Group Will Hold"
            >
              <Summary
                kind={kind}
                onKind={(next) => {
                  setKind(kind === next ? ALL : next)
                }}
                summary={summary}
              />
            </Section>
          ) : null}
          <Section count={liveCount(groupRows, "remove")} title="Removals">
            <ItemTable
              key={group}
              action="remove"
              disabled={disabled}
              kind={kind}
              onCancel={cancel}
              onEdit={edit}
              onKind={setKind}
              onUndo={undo}
              rows={groupRows.filter((row) => row.action === "remove")}
            />
          </Section>
          <Section count={liveCount(groupRows, "add")} title="Additions">
            <ItemTable
              key={group}
              action="add"
              disabled={disabled}
              kind={kind}
              onCancel={cancel}
              onEdit={edit}
              onKind={setKind}
              onUndo={undo}
              rows={groupRows.filter((row) => row.action === "add")}
            />
            <AddItem
              disabled={disabled}
              initialKind={ITEM_KINDS.find((item) => item === kind) ?? "HEADLINE"}
              onAdd={(itemKind, raw) => {
                save(addGroupItem(args, group, itemKind, raw))
              }}
            />
          </Section>
        </>
      ) : null}
      {groupsNeedCheck(args, checked) && counts.total > 0 ? (
        <CheckChanges
          canCheck={canCheckGroups(args)}
          disabled={disabled}
          label={groupCheckIncomplete(checked) ? "Check Again" : "Check Changes"}
          note="You changed this request, so Google needs to check it again."
          onCheck={controls.onReview}
          submitting={controls.submitting}
        />
      ) : null}
    </div>
  )
}

function liveCount(rows: readonly GroupChangeRow[], action: "add" | "remove"): number {
  return rows.filter((row) => row.action === action && !row.cancelled).length
}

function Section({
  aside,
  children,
  count,
  title,
}: {
  aside?: string
  children: ReactNode
  count?: number
  title: string
}) {
  return (
    <section aria-label={title} className="grid min-w-0 gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium">
          {title}
          {count !== undefined ? (
            <span className="text-muted-foreground ml-1.5 tabular-nums">{String(count)}</span>
          ) : null}
        </h3>
        {aside ? <p className="text-muted-foreground text-xs">{aside}</p> : null}
      </div>
      {children}
    </section>
  )
}

function isItemKind(value: unknown): value is ItemKind {
  return ITEM_KINDS.some((item) => item === value)
}

/** Each asset type's count now and after, against Google's limits; a click filters the tables. */
function Summary({
  kind,
  onKind,
  summary,
}: {
  kind: string
  onKind: (kind: ItemKind) => void
  summary: readonly KindSummary[]
}) {
  const byKind = new Map(summary.map((item) => [item.kind, item]))
  const rows: DataRow[] = summary.map((item) => ({
    adding: item.adding,
    after: item.after,
    allowed:
      item.minimum > 0
        ? `${String(item.minimum)} to ${String(item.maximum)}`
        : `Up to ${String(item.maximum)}`,
    key: item.kind,
    now: item.now,
    removing: item.removing,
    status: limitProblem(item) ?? "",
    type: `${GROUP_CHANGE_LABELS[item.kind]}s`,
  }))
  const itemOf = (row: DataRow) => (isItemKind(row["key"]) ? byKind.get(row["key"]) : undefined)
  return (
    <DataTable
      columns={SUMMARY_COLUMNS}
      onRowClick={(row) => {
        const item = itemOf(row)
        if (item) onKind(item.kind)
      }}
      pageSize={12}
      renderCell={(column, row) => {
        const item = itemOf(row)
        if (!item) return null
        if (column.key === "removing")
          return item.removing ? (
            <span className="text-warning-text tabular-nums">−{String(item.removing)}</span>
          ) : (
            <span className="text-muted-foreground">–</span>
          )
        if (column.key === "adding")
          return item.adding ? (
            <span className="text-success-text tabular-nums">+{String(item.adding)}</span>
          ) : (
            <span className="text-muted-foreground">–</span>
          )
        if (column.key === "after")
          return <span className="font-medium tabular-nums">{String(item.after)}</span>
        if (column.key === "status") return <LimitBadge item={item} />
        return null
      }}
      rowClassName={(row) =>
        row["key"] === kind ? "bg-muted/70 shadow-[inset_3px_0_0_var(--primary)]" : undefined
      }
      rowDetails={false}
      rowNoun={["asset type", "asset types"]}
      rows={rows}
    />
  )
}

function LimitBadge({ item }: { item: KindSummary }) {
  if (limitProblem(item))
    return item.after < item.minimum ? (
      <Badge variant="destructive">Needs {String(item.minimum - item.after)} More</Badge>
    ) : (
      <Badge variant="destructive">{String(item.after - item.maximum)} Over the Limit</Badge>
    )
  return item.adding || item.removing ? (
    <Badge variant="success">Within Limits</Badge>
  ) : (
    <Badge variant="secondary">No Change</Badge>
  )
}

/** The asset group's new name and final URL, each edited in place. */
function Settings({
  disabled,
  onCancel,
  onEdit,
  onUndo,
  rows,
}: {
  disabled: boolean
  onCancel: (ids: Iterable<string>) => void
  onEdit: (row: GroupChangeRow, next: unknown) => void
  onUndo: (row: GroupChangeRow) => void
  rows: readonly GroupChangeRow[]
}) {
  if (rows.length === 0) return null
  const byId = new Map(rows.map((row) => [row.id, row]))
  return (
    <Section title="Asset Group Settings">
      <DataTable
        columns={SETTING_COLUMNS}
        pageSize={5}
        renderCell={(column, data) => {
          const row = byId.get(String(data["key"]))
          if (!row) return null
          if (column.key === "value")
            return <ItemCell disabled={disabled} onEdit={onEdit} row={row} />
          if (column.key === "cancel")
            return (
              <CancelCell
                cancelled={row.cancelled}
                disabled={disabled}
                onCancel={() => {
                  onCancel([row.id])
                }}
                onUndo={() => {
                  onUndo(row)
                }}
              />
            )
          return null
        }}
        rowDetails={false}
        rowNoun={["setting", "settings"]}
        rows={rows.map((row) => ({
          cancel: "",
          key: row.id,
          now: row.before ?? "",
          setting: GROUP_CHANGE_LABELS[row.kind],
          value: row.value,
        }))}
      />
    </Section>
  )
}

function kindTabs(rows: readonly GroupChangeRow[]): DataTableTab[] {
  return [
    { id: ALL, label: "All", match: () => true },
    ...ITEM_KINDS.filter((item) => rows.some((row) => row.kind === item)).map((item) => ({
      id: item,
      label: `${GROUP_CHANGE_LABELS[item]}s`,
      match: (row: DataRow) => row["kind"] === item,
    })),
  ]
}

/** One table of removals or additions, filtered by asset type, with every addition editable. */
function ItemTable({
  action,
  disabled,
  kind,
  onCancel,
  onEdit,
  onKind,
  onUndo,
  rows,
}: {
  action: "add" | "remove"
  disabled: boolean
  kind: string
  onCancel: (ids: Iterable<string>) => void
  onEdit: (row: GroupChangeRow, next: unknown) => void
  onKind: (kind: string) => void
  onUndo: (row: GroupChangeRow) => void
  rows: readonly GroupChangeRow[]
}) {
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set())
  const byId = useMemo(() => new Map(rows.map((row) => [row.id, row])), [rows])
  const tabs = useMemo(() => kindTabs(rows), [rows])
  if (rows.length === 0)
    return (
      <p className="text-muted-foreground text-sm">
        {action === "add" ? "Nothing is added." : "Nothing is removed."}
      </p>
    )
  const tableRows: DataRow[] = rows.map((row) => ({
    asset: row.label,
    cancel: "",
    key: row.id,
    kind: row.kind,
    length: lengthText(row),
    type: GROUP_CHANGE_LABELS[row.kind],
  }))
  return (
    <DataTable
      activeTab={kind}
      columns={action === "add" ? ADDITION_COLUMNS : REMOVAL_COLUMNS}
      exportFilename={`google-ads-asset-group-${action === "add" ? "additions" : "removals"}.csv`}
      onTabChange={onKind}
      pageSize={10}
      renderCell={(column, data) => {
        const row = byId.get(String(data["key"]))
        if (!row) return null
        if (column.key === "asset")
          return action === "add" ? (
            <ItemCell disabled={disabled} onEdit={onEdit} row={row} />
          ) : (
            <ItemLabel row={row} />
          )
        if (column.key === "type")
          return (
            <Badge variant={action === "add" ? "success" : "warning"}>
              {GROUP_CHANGE_LABELS[row.kind]}
            </Badge>
          )
        if (column.key === "length")
          return (
            <span
              className={cn(
                "text-xs tabular-nums",
                tooLong(row) ? "text-destructive font-medium" : "text-muted-foreground"
              )}
            >
              {cellText(data["length"])}
            </span>
          )
        if (column.key === "cancel")
          return (
            <CancelCell
              cancelled={row.cancelled}
              disabled={disabled}
              onCancel={() => {
                onCancel([row.id])
              }}
              onUndo={() => {
                onUndo(row)
              }}
            />
          )
        return null
      }}
      rowClassName={(data) => (byId.get(String(data["key"]))?.cancelled ? "opacity-60" : undefined)}
      rowDetails={false}
      rowNoun={["change", "changes"]}
      rows={tableRows}
      tabs={tabs}
      {...(rows.length >= TOOLS_FROM
        ? {
            searchable: true,
            selection: {
              actions: (
                <Button
                  disabled={disabled}
                  onClick={() => {
                    onCancel(selected)
                    setSelected(new Set())
                  }}
                  size="sm"
                  type="button"
                  variant="outline"
                >
                  Cancel These Changes
                </Button>
              ),
              onChange: setSelected,
              rowId: (row: DataRow) => String(row["key"]),
              selected,
            },
          }
        : {})}
    />
  )
}

function tooLong(row: GroupChangeRow): boolean {
  const limit = TEXT_LIMITS[row.kind]
  return limit !== undefined && characterCount(row.value) > limit
}

function lengthText(row: GroupChangeRow): string {
  const limit = TEXT_LIMITS[row.kind]
  return limit === undefined || row.action !== "add"
    ? ""
    : `${String(characterCount(row.value))}/${String(limit)}`
}

function ItemLabel({ row }: { row: GroupChangeRow }) {
  return (
    <span className="grid min-w-0 gap-0.5 text-sm whitespace-normal">
      <span className={cn("wrap-anywhere", row.cancelled && "line-through")}>{row.label}</span>
      <Problem row={row} />
    </span>
  )
}

function Problem({ row }: { row: GroupChangeRow }) {
  return !row.cancelled && row.problem ? (
    <span className="text-destructive text-xs wrap-anywhere">{row.problem}</span>
  ) : null
}

/** Edits an addition or setting in place: text, an audience by search, or an image's shape. */
function ItemCell({
  disabled,
  onEdit,
  row,
}: {
  disabled: boolean
  onEdit: (row: GroupChangeRow, next: unknown) => void
  row: GroupChangeRow
}) {
  const [searching, setSearching] = useState(false)
  if (row.cancelled) return <ItemLabel row={row} />
  if (
    row.action === "set" ||
    TEXT_KINDS.some((item) => item === row.kind) ||
    row.kind === "search_theme"
  )
    return (
      <span className="grid min-w-0 gap-0.5">
        <CommittedInput
          ariaLabel={`${GROUP_CHANGE_LABELS[row.kind]}: ${row.label}`}
          disabled={disabled}
          onCommit={(value) => {
            onEdit(row, value)
          }}
          value={row.value}
        />
        <Problem row={row} />
      </span>
    )
  if (row.kind === "audience_signal")
    return (
      <span className="grid min-w-0 gap-1 text-sm">
        {searching ? (
          <AudienceSearch
            disabled={disabled}
            label={`Change ${row.label}`}
            onCancel={() => {
              setSearching(false)
            }}
            onChoose={(audience) => {
              onEdit(row, audience)
              setSearching(false)
            }}
          />
        ) : (
          <span className="flex min-w-0 items-center gap-2">
            <span className="min-w-0 flex-1 wrap-anywhere">{row.label}</span>
            <Button
              disabled={disabled}
              onClick={() => {
                setSearching(true)
              }}
              size="sm"
              type="button"
              variant="ghost"
            >
              Change
            </Button>
          </span>
        )}
        <Problem row={row} />
      </span>
    )
  const image = isRecord(row.raw) ? row.raw : null
  if (image && IMAGE_KINDS.some((item) => item === row.kind) && isItemKind(row.kind))
    return (
      <span className="grid min-w-0 gap-1 text-sm">
        <span className="flex min-w-0 items-center gap-2">
          <span className="min-w-0 flex-1 wrap-anywhere">{row.label}</span>
          <KindSelect
            disabled={disabled}
            kinds={IMAGE_KINDS}
            label={`Shape of ${row.label}`}
            onChange={(shape) => {
              onEdit(row, { ...image, field_type: shape })
            }}
            value={row.kind}
          />
        </span>
        <Problem row={row} />
      </span>
    )
  return <ItemLabel row={row} />
}

function KindSelect({
  disabled,
  kinds,
  label,
  onChange,
  value,
}: {
  disabled: boolean
  kinds: readonly ItemKind[]
  label: string
  onChange: (kind: ItemKind) => void
  value: ItemKind
}) {
  return (
    <Select<string>
      disabled={disabled}
      onValueChange={(next) => {
        const found = kinds.find((item) => item === next)
        if (found) onChange(found)
      }}
      value={value}
    >
      <SelectTrigger aria-label={label} className="w-44" size="sm">
        <SelectValue />
      </SelectTrigger>
      <SelectContent align="start">
        <SelectGroup>
          {kinds.map((item) => (
            <SelectItem key={item} label={GROUP_CHANGE_LABELS[item]} value={item}>
              {GROUP_CHANGE_LABELS[item]}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}

function AudienceSearch({
  disabled,
  label,
  onCancel,
  onChoose,
}: {
  disabled: boolean
  label: string
  onCancel?: () => void
  onChoose: (audience: Record<string, unknown>) => void
}) {
  return (
    <span className="flex items-end gap-2">
      <span className="min-w-0 flex-1">
        <EntitySearch
          disabled={disabled}
          entityKind="google_ads_audience"
          fieldKey={FIELD}
          // A combined audience can't be part of a signal.
          isTaken={(choice) => !AUDIENCE_KINDS.includes(choice.value["kind"])}
          label={label}
          onChoose={(choice) => {
            onChoose({ key: choice.value["key"], kind: choice.value["kind"], name: choice.label })
          }}
          placeholder="Search your lists, interests, and custom audiences"
          searchRequired
          toolName={TOOL}
        />
      </span>
      {onCancel ? (
        <Button onClick={onCancel} size="sm" type="button" variant="ghost">
          Cancel
        </Button>
      ) : null}
    </span>
  )
}

/** Adds one item of any type: typed text, an audience, or an uploaded image or video. */
function AddItem({
  disabled,
  initialKind,
  onAdd,
}: {
  disabled: boolean
  initialKind: ItemKind
  onAdd: (kind: ItemKind, raw: unknown) => void
}) {
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState<ItemKind>(initialKind)
  const [text, setText] = useState("")
  const close = () => {
    setText("")
    setOpen(false)
  }
  if (!open)
    return (
      <Button
        className="w-fit"
        disabled={disabled}
        onClick={() => {
          setKind(initialKind)
          setOpen(true)
        }}
        size="sm"
        type="button"
        variant="outline"
      >
        <PlusIcon />
        Add an Item
      </Button>
    )
  const typed = TEXT_KINDS.some((item) => item === kind) || kind === "search_theme"
  const video = kind === "YOUTUBE_VIDEO"
  return (
    <div className="flex flex-wrap items-end gap-2 rounded-lg border p-2">
      <KindSelect
        disabled={disabled}
        kinds={ITEM_KINDS}
        label="Type to add"
        onChange={setKind}
        value={kind}
      />
      <div className="min-w-60 flex-1">
        {typed ? (
          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault()
              if (text.trim()) onAdd(kind, text.trim())
              close()
            }}
          >
            <Input
              aria-label={`New ${GROUP_CHANGE_LABELS[kind].toLowerCase()}`}
              className="h-8"
              disabled={disabled}
              onChange={(event) => {
                setText(event.currentTarget.value)
              }}
              placeholder={`New ${GROUP_CHANGE_LABELS[kind].toLowerCase()}`}
              value={text}
            />
            <Button disabled={disabled || !text.trim()} size="sm" type="submit">
              Add
            </Button>
          </form>
        ) : kind === "audience_signal" ? (
          <AudienceSearch
            disabled={disabled}
            label="Search for an audience"
            onChoose={(audience) => {
              onAdd(kind, audience)
              close()
            }}
          />
        ) : (
          <EntitySearch
            disabled={disabled}
            entityKind="google_ads_asset"
            fieldKey={FIELD}
            isTaken={(choice) => choice.value["asset_type"] !== (video ? "YOUTUBE_VIDEO" : "IMAGE")}
            label={video ? "Search uploaded videos" : "Search uploaded images"}
            onChoose={(choice) => {
              onAdd(kind, video ? choice.value : { asset: choice.value, field_type: kind })
              close()
            }}
            placeholder="Search by name"
            toolName={TOOL}
          />
        )}
      </div>
      <Button onClick={close} size="sm" type="button" variant="ghost">
        Cancel
      </Button>
    </div>
  )
}
