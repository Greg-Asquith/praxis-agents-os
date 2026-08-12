// apps/web/src/components/data-table/data-table-pagination.tsx

import { appTableContexts } from "@/components/data-table/contexts"
import {
  paginationStateFromServer,
  paginationStateToServer,
} from "@/components/data-table/server-state"
import { PaginationControls } from "@/components/ui/pagination-controls"

type DataTablePaginationProps = {
  ariaLabel?: string
  disabled?: boolean
  total?: number
}

export function DataTablePagination({
  ariaLabel,
  disabled = false,
  total,
}: DataTablePaginationProps) {
  const table = appTableContexts.useTableContext()
  const pagination = table.state.pagination
  const resolvedTotal = total ?? table.getRowCount()

  return (
    <PaginationControls
      {...(ariaLabel === undefined ? {} : { ariaLabel })}
      disabled={disabled}
      limit={pagination.pageSize}
      offset={paginationStateToServer(pagination).offset}
      onPageChange={(offset) => {
        table.setPagination(
          paginationStateFromServer({ limit: pagination.pageSize, offset }, resolvedTotal)
        )
      }}
      total={resolvedTotal}
    />
  )
}
