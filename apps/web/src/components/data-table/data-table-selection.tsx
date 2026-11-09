// apps/web/src/components/data-table/data-table-selection.tsx

import type { ReactNode } from "react"

import { Button } from "@/components/ui/button"

export type DataTableSelection = {
  // Bulk buttons shown beside the count while any row is selected.
  actions: ReactNode
  onChange: (selected: Set<string>) => void
  rowId: (row: Record<string, unknown>) => string
  selected: ReadonlySet<string>
}

/** The bar above a table while rows are selected. */
export function DataTableBulkBar({
  actions,
  count,
  onClear,
}: {
  actions: ReactNode
  count: number
  onClear: () => void
}) {
  return (
    <div
      className="bg-muted/60 flex flex-wrap items-center gap-2 rounded-lg px-3 py-1.5"
      role="toolbar"
      aria-label="Bulk actions"
    >
      <span className="text-sm font-medium tabular-nums">{String(count)} selected</span>
      {actions}
      <Button className="ml-auto" onClick={onClear} size="sm" type="button" variant="ghost">
        Clear
      </Button>
    </div>
  )
}
