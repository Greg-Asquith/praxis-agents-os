// apps/web/src/components/data-table/data-table-sort-menu.tsx

import { ArrowUpDownIcon, CheckIcon } from "lucide-react"

import { appTableContexts } from "@/components/data-table/contexts"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"

type DataTableSortMenuProps = {
  className?: string
  disabled?: boolean
}

export function DataTableSortMenu({ className, disabled = false }: DataTableSortMenuProps) {
  const table = appTableContexts.useTableContext()
  const sortableColumns = table.getAllLeafColumns().filter((column) => column.getCanSort())
  const sorting = table.state.sorting[0]
  const activeColumn = sorting ? table.getColumn(sorting.id) : undefined
  const activeLabel = activeColumn?.columnDef.meta?.label ?? activeColumn?.id ?? "None"

  return (
    <div className={cn("flex justify-end", className)}>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button disabled={disabled} size="sm" type="button" variant="outline">
              <ArrowUpDownIcon data-icon="inline-start" />
              Sort: {activeLabel}
            </Button>
          }
        />
        <DropdownMenuContent align="end">
          <DropdownMenuGroup>
            <DropdownMenuLabel>Sort by</DropdownMenuLabel>
            {sortableColumns.map((column) => {
              const label = column.columnDef.meta?.label ?? column.id
              return (
                <DropdownMenuItem
                  key={column.id}
                  onClick={() => {
                    column.toggleSorting(column.getFirstSortDir() === "desc")
                  }}
                >
                  {label}
                  {sorting?.id === column.id ? <CheckIcon className="ml-auto" /> : null}
                </DropdownMenuItem>
              )
            })}
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuLabel>Direction</DropdownMenuLabel>
            <DropdownMenuItem
              disabled={!activeColumn}
              onClick={() => {
                activeColumn?.toggleSorting(false)
              }}
            >
              Ascending
              {sorting && !sorting.desc ? <CheckIcon className="ml-auto" /> : null}
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={!activeColumn}
              onClick={() => {
                activeColumn?.toggleSorting(true)
              }}
            >
              Descending
              {sorting?.desc ? <CheckIcon className="ml-auto" /> : null}
            </DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
