// apps/web/src/integrations/google_ads/components/remove-objects-approval.tsx

import { XIcon } from "lucide-react"
import { useMemo, useState } from "react"

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Button } from "@/components/ui/button"
import {
  DataTable,
  type DataColumn,
  type DataRow,
  type DataTableTab,
} from "@/components/ui/data-table"
import { AttentionLine } from "@/integrations/ads/components/attention-line"
import { ChangeBanner } from "@/integrations/ads/components/change-banner"
import { ChangeSummary, type ChangeSummaryLine } from "@/integrations/ads/components/change-summary"
import {
  editedItems,
  kindDetail,
  REMOVAL_KIND_TITLES,
  REMOVAL_KINDS,
  removalBannerDetail,
  removalCounts,
  removalRows,
  type RemovalKind,
  type RemovalRow,
  type RemoveObjectsArgs,
} from "@/integrations/google_ads/lib/remove-objects"

// Below this many items the summary and the table tools only add noise.
const TOOLS_FROM = 10

const COLUMNS: DataColumn[] = [
  { key: "item", kind: "text", label: "Item", width: 300 },
  { key: "kind", kind: "text", label: "Kind", width: 120 },
  { key: "campaign", kind: "text", label: "Campaign", width: 200 },
  { key: "also", kind: "text", label: "Also Removes", width: 200 },
  { key: "cancel", kind: "text", label: "Cancel", width: 90 },
]

export function RemoveObjectsApproval({
  args,
  disabled,
  onFieldEdit,
  proposed,
}: {
  args: RemoveObjectsArgs
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
  proposed: RemoveObjectsArgs
}) {
  const [tab, setTab] = useState("all")
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set())
  const rows = useMemo(() => removalRows(proposed, args), [proposed, args])
  const counts = removalCounts(rows)
  const byKey = useMemo(() => new Map(rows.map((row) => [row.key, row])), [rows])
  const tools = rows.length >= TOOLS_FROM
  const tabs = useMemo(() => removalTabs(byKey), [byKey])
  const tableRows = useMemo<DataRow[]>(
    () =>
      rows.map((row) => ({
        also: row.alsoRemoves || "—",
        campaign: row.campaignName ?? "—",
        cancel: "",
        item: row.name,
        key: row.key,
        kind: REMOVAL_KIND_TITLES[row.item.kind].one,
      })),
    [rows]
  )

  const edit = (keys: Iterable<string>, cancelled: boolean) => {
    onFieldEdit("items", editedItems(rows, new Set(keys), cancelled))
  }
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
  const kindLine = (kind: RemovalKind) => {
    const detail = kindDetail(kind, rows)
    return lineFor(kind, REMOVAL_KIND_TITLES[kind].many, counts.byKind[kind], {
      ...(detail ? { detail } : {}),
    })
  }

  return (
    <div className="grid min-w-0 gap-3">
      <ChangeBanner
        detail={removalBannerDetail(counts)}
        title="Removal can't be undone"
        tone="danger"
      />
      {tools ? (
        <>
          <ChangeSummary
            lines={[
              ...REMOVAL_KINDS.map(kindLine),
              lineFor("attention", "Needs Attention", counts.problems, {
                tone: "danger",
                action: (
                  <Button
                    disabled={disabled}
                    onClick={() => {
                      edit(
                        rows.filter((row) => !row.cancelled && row.problem).map((row) => row.key),
                        true
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
        exportFilename="google-ads-removals.csv"
        onTabChange={setTab}
        pageSize={25}
        renderCell={(column, row) => {
          const removal = byKey.get(String(row["key"]))
          if (!removal) return null
          if (column.key === "item") return <ItemCell row={removal} />
          if (column.key === "cancel")
            return (
              <CancelCell
                disabled={disabled}
                onToggle={(cancelled) => {
                  edit([removal.key], cancelled)
                }}
                row={removal}
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
                  <Button
                    disabled={disabled}
                    onClick={() => {
                      edit(selected, true)
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

function removalTabs(byKey: ReadonlyMap<string, RemovalRow>): DataTableTab[] {
  const live = (row: DataRow, match: (removal: RemovalRow) => boolean) => {
    const removal = byKey.get(String(row["key"]))
    return removal !== undefined && !removal.cancelled && match(removal)
  }
  return [
    { id: "all", label: "All", match: () => true },
    ...REMOVAL_KINDS.map((kind) => ({
      id: kind,
      label: REMOVAL_KIND_TITLES[kind].many,
      hideWhenEmpty: true,
      match: (row: DataRow) => live(row, (removal) => removal.item.kind === kind),
    })),
    {
      id: "attention",
      label: "Needs Attention",
      hideWhenEmpty: true,
      match: (row) => live(row, (removal) => removal.problem !== null),
    },
  ]
}

function ItemCell({ row }: { row: RemovalRow }) {
  const showsGroup = row.item.kind === "ad" || row.item.kind === "keyword"
  return (
    <div className="grid min-w-0 gap-0.5 text-sm">
      <span className="font-medium wrap-anywhere">{row.name}</span>
      {showsGroup && row.groupName ? (
        <span className="text-muted-foreground text-xs wrap-anywhere">{row.groupName}</span>
      ) : null}
      {!row.cancelled && row.problem ? (
        <span className="text-destructive text-xs wrap-anywhere">{row.problem}</span>
      ) : null}
      {!row.cancelled && row.alreadyRemoved && !row.problem ? (
        <span className="text-muted-foreground text-xs">Already removed in Google Ads.</span>
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
  row: RemovalRow
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
      aria-label="Cancel This Change"
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
