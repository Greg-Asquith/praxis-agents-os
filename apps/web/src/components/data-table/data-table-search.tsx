// apps/web/src/components/data-table/data-table-search.tsx

import { appTableContexts } from "@/components/data-table/contexts"
import { Input } from "@/components/ui/input"

type DataTableSearchProps = {
  ariaLabel?: string
  className?: string
  disabled?: boolean
  placeholder?: string
}

export function DataTableSearch({
  ariaLabel = "Search table",
  className,
  disabled = false,
  placeholder = "Search…",
}: DataTableSearchProps) {
  const table = appTableContexts.useTableContext()

  return (
    <Input
      aria-label={ariaLabel}
      className={className}
      disabled={disabled}
      onChange={(event) => {
        table.setGlobalFilter(event.target.value)
      }}
      placeholder={placeholder}
      type="search"
      value={String(table.state.globalFilter ?? "")}
    />
  )
}
