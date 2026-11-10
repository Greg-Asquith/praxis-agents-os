// apps/web/src/integrations/ads/components/parent-table.tsx

import { useMemo } from "react"

import { Button } from "@/components/ui/button"
import {
  DataTable,
  type DataColumn,
  type DataRow,
  type DataTableTab,
} from "@/components/ui/data-table"

// Below this many parents the table's search and tabs only add noise.
const TOOLS_FROM = 10

export type ParentRow = {
  key: string
  name: string
  // Where the parent sits, such as an ad group's campaign.
  context?: string | null
  // How many of its changes need fixing or cancelling.
  problems: number
  cancelled: boolean
  // The values of the caller's own columns, by column key.
  values: DataRow
}

const TABS: DataTableTab[] = [
  { id: "all", label: "All", match: () => true },
  {
    id: "attention",
    label: "Needs Attention",
    hideWhenEmpty: true,
    match: (row) => row["attention"] === "yes",
  },
]

/** The campaigns, ad groups, or lists a card changes, above the table of the changes in them. */
export function ParentTable({
  columns,
  disabled,
  label,
  onCancel,
  onSelect,
  onUndo,
  rowNoun,
  rows,
  selected,
}: {
  // The caller's columns, between the name and Cancel.
  columns: DataColumn[]
  disabled: boolean
  label: string
  onCancel: (key: string) => void
  // A click selects a parent, so the changes below show only its own; again shows them all.
  onSelect: (key: string | null) => void
  onUndo: (key: string) => void
  rowNoun: readonly [singular: string, plural: string]
  rows: readonly ParentRow[]
  selected: string | null
}) {
  const byKey = useMemo(() => new Map(rows.map((row) => [row.key, row])), [rows])
  const allColumns = useMemo<DataColumn[]>(
    () => [
      { key: "name", kind: "text", label: label, width: 240 },
      ...columns,
      { key: "cancel", kind: "text", label: "Cancel", width: 150 },
    ],
    [columns, label]
  )
  const tableRows = useMemo<DataRow[]>(
    () =>
      rows.map((row) => ({
        ...row.values,
        attention: row.problems > 0 && !row.cancelled ? "yes" : "no",
        cancel: "",
        key: row.key,
        name: row.name,
      })),
    [rows]
  )
  const tools = rows.length >= TOOLS_FROM
  return (
    <section aria-label={label} className="grid min-w-0 gap-1.5">
      <DataTable
        columns={allColumns}
        onRowClick={(row) => {
          const key = String(row["key"])
          onSelect(key === selected ? null : key)
        }}
        pageSize={25}
        renderCell={(column, row) => {
          const parent = byKey.get(String(row["key"]))
          if (!parent) return null
          if (column.key === "name") return <ParentCell row={parent} />
          if (column.key !== "cancel") return null
          return (
            <Button
              disabled={disabled}
              onClick={(event) => {
                // The row selects the parent on click; cancelling shouldn't.
                event.stopPropagation()
                if (parent.cancelled) onUndo(parent.key)
                else onCancel(parent.key)
              }}
              size="sm"
              type="button"
              variant="ghost"
            >
              {parent.cancelled ? "Undo" : "Cancel This Change"}
            </Button>
          )
        }}
        rowClassName={(row) => {
          const parent = byKey.get(String(row["key"]))
          if (parent?.cancelled) return "opacity-60"
          return parent?.key === selected
            ? "bg-muted/70 shadow-[inset_3px_0_0_var(--primary)]"
            : undefined
        }}
        rowDetails={false}
        rowNoun={rowNoun}
        rows={tableRows}
        {...(tools ? { searchable: true, tabs: TABS } : {})}
      />
    </section>
  )
}

function ParentCell({ row }: { row: ParentRow }) {
  return (
    <span className="grid min-w-0 gap-0.5 whitespace-normal">
      <span className="font-medium wrap-anywhere">{row.name}</span>
      {row.context ? (
        <span className="text-muted-foreground text-xs wrap-anywhere">{row.context}</span>
      ) : null}
      {!row.cancelled && row.problems > 0 ? (
        <span className="text-destructive text-xs">Needs Attention</span>
      ) : null}
    </span>
  )
}
