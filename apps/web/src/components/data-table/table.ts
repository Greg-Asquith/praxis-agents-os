// apps/web/src/components/data-table/table.ts

import { createTableHook } from "@tanstack/react-table"

import { DataTableColumnHeader } from "@/components/data-table/data-table-column-header"
import { DataTablePagination } from "@/components/data-table/data-table-pagination"
import { DataTableSearch } from "@/components/data-table/data-table-search"
import { DataTableSortMenu } from "@/components/data-table/data-table-sort-menu"
import { DataTableViewOptions } from "@/components/data-table/data-table-view-options"
import { appTableContexts } from "@/components/data-table/contexts"
import { appTableFeatures } from "@/components/data-table/features"

const appTable = createTableHook({
  features: appTableFeatures,
  tableContext: appTableContexts.tableContext,
  cellContext: appTableContexts.cellContext,
  headerContext: appTableContexts.headerContext,
  defaultColumn: {
    enableHiding: false,
    enableSorting: false,
  },
  getRowId: (row: { id: string }) => row.id,
  headerComponents: { ColumnHeader: DataTableColumnHeader },
  tableComponents: {
    Pagination: DataTablePagination,
    Search: DataTableSearch,
    SortMenu: DataTableSortMenu,
    ViewOptions: DataTableViewOptions,
  },
})

export const {
  createAppColumnHelper,
  useAppTable,
  useCellContext,
  useHeaderContext,
  useTableContext,
} = appTable
