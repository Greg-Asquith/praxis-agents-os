// apps/web/src/components/data-table/data-table-view-options.tsx

import { SlidersHorizontalIcon } from "lucide-react"

import { appTableContexts } from "@/components/data-table/contexts"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

export function DataTableViewOptions() {
  const table = appTableContexts.useTableContext()
  const hideableColumns = table.getAllLeafColumns().filter((column) => column.getCanHide())
  const visibleColumnCount = table.getVisibleLeafColumns().length

  if (hideableColumns.length < 2) {
    return null
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button aria-label="Choose report columns" size="icon-xs" type="button" variant="ghost">
            <SlidersHorizontalIcon />
          </Button>
        }
      />
      <DropdownMenuContent align="end">
        <DropdownMenuGroup>
          <DropdownMenuLabel>Columns</DropdownMenuLabel>
          {hideableColumns.map((column) => (
            <DropdownMenuCheckboxItem
              checked={column.getIsVisible()}
              disabled={column.getIsVisible() && visibleColumnCount === 1}
              key={column.id}
              onCheckedChange={(visible) => {
                column.toggleVisibility(visible)
              }}
            >
              {column.columnDef.meta?.label ?? column.id}
            </DropdownMenuCheckboxItem>
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
