// apps/web/src/integrations/google_ads/components/status-change-approval.tsx

import { XIcon } from "lucide-react"
import { useMemo, useState } from "react"

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DataTable,
  type DataColumn,
  type DataRow,
  type DataTableGroup,
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
import { AttentionLine } from "@/integrations/ads/components/attention-line"
import { ChangeBanner } from "@/integrations/ads/components/change-banner"
import { ChangeSummary, type ChangeSummaryLine } from "@/integrations/ads/components/change-summary"
import { SegmentedChoice } from "@/integrations/ads/components/controls"
import {
  editedChanges,
  STATUS_KIND_TITLES,
  statusBannerDetail,
  statusCounts,
  statusLabel,
  statusRows,
  type RequestedStatus,
  type StatusChangeArgs,
  type StatusPatch,
  type StatusRow,
} from "@/integrations/google_ads/lib/status-change"

// Below this many items the summary and the table tools only add noise.
const TOOLS_FROM = 10

const COLUMNS: DataColumn[] = [
  { key: "item", kind: "text", label: "Item", width: 300 },
  { key: "kind", kind: "text", label: "Kind", width: 110 },
  { key: "status", kind: "text", label: "Status", width: 230 },
  { key: "campaign", kind: "text", label: "Campaign", hidden: true },
  { key: "cancel", kind: "text", label: "Cancel", width: 90 },
]

const STATUS_OPTIONS: readonly { value: RequestedStatus; label: string }[] = [
  { value: "ENABLED", label: "On" },
  { value: "PAUSED", label: "Off" },
]

export function StatusChangeApproval({
  args,
  disabled,
  onFieldEdit,
  proposed,
}: {
  args: StatusChangeArgs
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
  proposed: StatusChangeArgs
}) {
  const [tab, setTab] = useState("all")
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set())
  const rows = useMemo(() => statusRows(proposed, args), [proposed, args])
  const counts = statusCounts(rows)
  const byKey = useMemo(() => new Map(rows.map((row) => [row.key, row])), [rows])
  const tools = rows.length >= TOOLS_FROM
  const tabs = useMemo(() => statusTabs(byKey), [byKey])
  const tableRows = useMemo<DataRow[]>(
    () =>
      rows.map((row) => ({
        campaign: row.campaignName,
        cancel: "",
        item: row.item.label,
        key: row.key,
        kind: STATUS_KIND_TITLES[row.item.kind],
        status: statusLabel(row.status),
      })),
    [rows]
  )
  const accountIds = [
    ...new Set(rows.filter((row) => !row.cancelled).map((row) => row.item.customerId)),
  ]
  const groupBy = useMemo<DataTableGroup>(
    () => ({
      key: (row) => {
        const item = byKey.get(String(row["key"]))?.item
        return item ? `${item.customerId}:${item.campaignId}` : ""
      },
      label: (key, groupRows) =>
        groupLabel(byKey, groupRows[0], args.accounts, accountIds.length > 1, key),
    }),
    [accountIds.length, args.accounts, byKey]
  )

  const edit = (keys: Iterable<string>, patch: StatusPatch) => {
    onFieldEdit("changes", editedChanges(rows, new Set(keys), patch))
  }
  const keysOf = (match: (row: StatusRow) => boolean) =>
    rows.filter((row) => !row.cancelled && match(row)).map((row) => row.key)
  const lineFor = (
    id: string,
    label: string,
    count: number,
    extra: Partial<ChangeSummaryLine> = {}
  ): ChangeSummaryLine => ({
    count,
    id,
    label,
    onSelect: () => {
      setTab(id)
    },
    selected: tab === id,
    ...extra,
  })
  const setEvery = (change: StatusRow["change"], current: RequestedStatus) => (
    <SegmentedChoice
      ariaLabel={`Set every item to turn ${current === "ENABLED" ? "on" : "off"} to`}
      disabled={disabled}
      onChange={(status: RequestedStatus) => {
        edit(
          keysOf((row) => row.change === change),
          { status }
        )
      }}
      options={STATUS_OPTIONS}
      value={current}
    />
  )

  return (
    <div className="grid min-w-0 gap-3">
      <ChangeBanner
        aside={
          <p className="text-sm font-medium tabular-nums">
            {String(counts.turnOff)} off · {String(counts.turnOn)} on
          </p>
        }
        detail={statusBannerDetail(counts, accountIds, args.accounts)}
      />
      {tools ? (
        <>
          <ChangeSummary
            lines={[
              lineFor("turn_off", "Turn Off", counts.turnOff, {
                action: setEvery("turn_off", "PAUSED"),
              }),
              lineFor("turn_on", "Turn On", counts.turnOn, {
                action: setEvery("turn_on", "ENABLED"),
              }),
              lineFor("wont_show", "Won't Show Yet", counts.wontShow, { tone: "warning" }),
              lineFor("attention", "Needs Attention", counts.problems, {
                tone: "danger",
                action: (
                  <Button
                    disabled={disabled}
                    onClick={() => {
                      edit(
                        keysOf((row) => row.problem !== null),
                        { cancelled: true }
                      )
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
              setTab("attention")
            }}
          />
        </>
      ) : null}
      <DataTable
        activeTab={tab}
        columns={COLUMNS}
        exportFilename="google-ads-status-changes.csv"
        groupBy={groupBy}
        onTabChange={setTab}
        pageSize={25}
        renderCell={(column, row) => {
          const statusRow = byKey.get(String(row["key"]))
          if (!statusRow) return null
          if (column.key === "item") return <ItemCell row={statusRow} />
          if (column.key === "status")
            return (
              <StatusCell
                disabled={disabled}
                onChange={(status) => {
                  edit([statusRow.key], { status })
                }}
                row={statusRow}
              />
            )
          if (column.key === "cancel")
            return (
              <CancelCell
                disabled={disabled}
                onToggle={(cancelled) => {
                  edit([statusRow.key], { cancelled })
                }}
                row={statusRow}
              />
            )
          return null
        }}
        rowClassName={(row) =>
          byKey.get(String(row["key"]))?.cancelled ? "opacity-60" : undefined
        }
        rowDetails={false}
        rowNoun={["item", "items"]}
        rows={tableRows}
        {...(tools
          ? {
              searchable: true,
              selection: {
                actions: (
                  <>
                    {STATUS_OPTIONS.map((option) => (
                      <Button
                        key={option.value}
                        disabled={disabled}
                        onClick={() => {
                          edit(selected, { status: option.value })
                          setSelected(new Set())
                        }}
                        size="sm"
                        type="button"
                        variant="outline"
                      >
                        Set to {option.label}
                      </Button>
                    ))}
                    <Button
                      disabled={disabled}
                      onClick={() => {
                        edit(selected, { cancelled: true })
                        setSelected(new Set())
                      }}
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
    </div>
  )
}

function statusTabs(byKey: ReadonlyMap<string, StatusRow>): DataTableTab[] {
  const live = (row: DataRow, match: (statusRow: StatusRow) => boolean) => {
    const statusRow = byKey.get(String(row["key"]))
    return statusRow !== undefined && !statusRow.cancelled && match(statusRow)
  }
  return [
    { id: "all", label: "All", match: () => true },
    {
      id: "turn_off",
      label: "Turn Off",
      match: (row) => live(row, (r) => r.change === "turn_off"),
    },
    { id: "turn_on", label: "Turn On", match: (row) => live(row, (r) => r.change === "turn_on") },
    {
      id: "wont_show",
      label: "Won't Show Yet",
      match: (row) => live(row, (r) => r.wontShow !== null),
    },
    {
      id: "attention",
      label: "Needs Attention",
      hideWhenEmpty: true,
      match: (row) => live(row, (r) => r.problem !== null),
    },
  ]
}

function groupLabel(
  byKey: ReadonlyMap<string, StatusRow>,
  first: DataRow | undefined,
  accounts: StatusChangeArgs["accounts"],
  showAccount: boolean,
  key: string
) {
  const row = first ? byKey.get(String(first["key"])) : undefined
  if (!row) return key
  const account = showAccount ? accounts.get(row.item.customerId)?.label : undefined
  const state = row.campaignOn === null ? null : `campaign is ${row.campaignOn ? "on" : "off"}`
  return (
    <span className="wrap-anywhere">
      {row.campaignName}
      {account ? ` · ${account}` : ""}
      {state ? <span className="text-muted-foreground font-normal"> · {state}</span> : null}
    </span>
  )
}

function ItemCell({ row }: { row: StatusRow }) {
  const showsGroup = row.item.kind === "ad" || row.item.kind === "keyword"
  return (
    <div className="grid min-w-0 gap-0.5 text-sm">
      <span className="font-medium wrap-anywhere">{row.item.label}</span>
      {showsGroup && row.groupName ? (
        <span className="text-muted-foreground text-xs wrap-anywhere">{row.groupName}</span>
      ) : null}
      {!row.cancelled && row.problem ? (
        <span className="text-destructive text-xs wrap-anywhere">{row.problem}</span>
      ) : null}
      {!row.cancelled && row.wontShow ? (
        <span className="text-warning-text text-xs wrap-anywhere">{row.wontShow}</span>
      ) : null}
    </div>
  )
}

function StatusCell({
  disabled,
  onChange,
  row,
}: {
  disabled: boolean
  onChange: (status: RequestedStatus) => void
  row: StatusRow
}) {
  if (row.cancelled) {
    return (
      <span className="text-muted-foreground text-sm line-through">
        {statusLabel(row.was)} → {statusLabel(row.status)}
      </span>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-muted-foreground">{statusLabel(row.was)} →</span>
      <Select<RequestedStatus>
        disabled={disabled}
        onValueChange={(next) => {
          if (next !== null) onChange(next)
        }}
        value={row.status}
      >
        <SelectTrigger aria-label={`New status for ${row.item.label}`} size="sm">
          <SelectValue />
        </SelectTrigger>
        <SelectContent align="start">
          <SelectGroup>
            {STATUS_OPTIONS.map((option) => (
              <SelectItem key={option.value} label={option.label} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
      {row.change === "already_set" ? (
        <Badge variant="secondary">{row.status === "ENABLED" ? "Already On" : "Already Off"}</Badge>
      ) : null}
    </div>
  )
}

function CancelCell({
  disabled,
  onToggle,
  row,
}: {
  disabled: boolean
  onToggle: (cancelled: boolean) => void
  row: StatusRow
}) {
  return row.cancelled ? (
    <Button
      disabled={disabled}
      onClick={() => {
        onToggle(false)
      }}
      size="sm"
      type="button"
      variant="ghost"
    >
      Undo
    </Button>
  ) : (
    <Button
      aria-label="Cancel this change"
      disabled={disabled}
      onClick={() => {
        onToggle(true)
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
