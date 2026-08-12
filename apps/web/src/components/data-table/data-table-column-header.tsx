// apps/web/src/components/data-table/data-table-column-header.tsx

import { ArrowDownIcon, ArrowUpDownIcon, ArrowUpIcon } from "lucide-react"

import { appTableContexts } from "@/components/data-table/contexts"
import { Button } from "@/components/ui/button"
import { TableHead } from "@/components/ui/table"

export function DataTableColumnHeader() {
  const header = appTableContexts.useHeaderContext()
  const { column } = header
  const meta = column.columnDef.meta
  const canSort = column.getCanSort()
  const label = meta?.label ?? column.id
  const sorted = column.getIsSorted()

  if (!canSort) {
    return <TableHead className={meta?.headClassName}>{label}</TableHead>
  }

  const ariaSort = sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"
  const SortIcon =
    sorted === "asc" ? ArrowUpIcon : sorted === "desc" ? ArrowDownIcon : ArrowUpDownIcon

  return (
    <TableHead aria-sort={ariaSort} className={meta?.headClassName}>
      <Button
        className="-ml-2"
        onClick={column.getToggleSortingHandler()}
        size="sm"
        type="button"
        variant="ghost"
      >
        {label}
        <SortIcon aria-hidden="true" data-icon="inline-end" />
      </Button>
    </TableHead>
  )
}
