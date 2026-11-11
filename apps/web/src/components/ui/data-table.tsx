// apps/web/src/components/ui/data-table.tsx

import { useEffect, useMemo, useState, type KeyboardEvent, type ReactNode } from "react"
import { CheckIcon, CopyIcon, DownloadIcon, ExternalLinkIcon } from "lucide-react"

import {
  createAppColumnHelper,
  useAppTable,
  useCellContext,
  useHeaderContext,
} from "@/components/data-table/table"
import { handleRowKeyDown } from "@/components/data-table/row-activation"
import {
  filterDataRows,
  orderByGroup,
  tabCounts,
  type DataTableGroup,
  type DataTableTab,
} from "@/components/data-table/filter"
import {
  DataTableBulkBar,
  type DataTableSelection,
} from "@/components/data-table/data-table-selection"
import { DataTableToolbar } from "@/components/data-table/data-table-toolbar"
import { safeHttpUrl } from "@/components/tool-ui/field-resolution"
import {
  dataTableExport,
  dataTableTotals,
  formatDataCell,
  type DataColumn,
  type DataRow,
} from "@/components/ui/data-table-model"
import { nodeText } from "@/components/tool-ui/untrusted-node"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Sparkline } from "@/components/ui/sparkline"
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { titleCaseToken } from "@/lib/format"
import { useClipboardCopy } from "@/hooks/use-clipboard-copy"
import { downloadTableCsv, tableToTsv } from "@/lib/table-export"
import { cn } from "@/lib/utils"

export type { DataTableGroup, DataTableTab } from "@/components/data-table/filter"
export type { DataTableSelection } from "@/components/data-table/data-table-selection"
export {
  isMicrosColumnKey,
  type DataColumn,
  type DataColumnKind,
  type DataRow,
} from "@/components/ui/data-table-model"

type DataTableTableRow = {
  id: string
  values: DataRow
}

const columnHelper = createAppColumnHelper<DataTableTableRow>()
const ROW_NOUN = ["row", "rows"] as const
const textCollator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" })

export function DataTable({
  activeTab,
  columns,
  exportFilename = "report.csv",
  groupBy,
  onRowClick,
  onTabChange,
  pageSize,
  renderCell,
  rowClassName,
  rowDetails = true,
  rowNoun = ROW_NOUN,
  rows,
  searchable = false,
  selection,
  showTotals = false,
  summary,
  tabs,
  truncationNote,
}: {
  // Controlled tab; without it the table keeps the first tab, or `defaultTab`, itself.
  activeTab?: string
  columns: DataColumn[]
  exportFilename?: string
  // Gathers rows under a heading row and turns column sorting off.
  groupBy?: DataTableGroup
  // Clicking a row calls this instead of opening the details sheet.
  onRowClick?: (row: DataRow) => void
  onTabChange?: (id: string) => void
  pageSize?: number
  // Cells may hold controls; pair them with `rowDetails={false}` so clicks don't open the sheet.
  renderCell?: (column: DataColumn, row: DataRow) => ReactNode | null
  rowClassName?: (row: DataRow) => string | undefined
  // Clicking a row opens a sheet with every field; on by default.
  rowDetails?: boolean
  rowNoun?: readonly [singular: string, plural: string]
  rows: DataRow[]
  searchable?: boolean
  // Adds a checkbox column and a bulk bar; the caller owns the selected ids.
  selection?: DataTableSelection
  showTotals?: boolean
  summary?: ReactNode
  // Filter tabs with counts; the export still holds every row.
  tabs?: readonly DataTableTab[]
  truncationNote?: string | null
}) {
  const { copied, copy } = useClipboardCopy()
  const [selectedRow, setSelectedRow] = useState<DataRow | null>(null)
  const [search, setSearch] = useState("")
  const [ownTab, setOwnTab] = useState<string | undefined>(undefined)
  const visibleTabs = useMemo(() => {
    const counts = tabs ? tabCounts(rows, tabs) : new Map<string, number>()
    return {
      counts,
      tabs: (tabs ?? []).filter((tab) => !tab.hideWhenEmpty || (counts.get(tab.id) ?? 0) > 0),
    }
  }, [rows, tabs])
  const currentTab =
    visibleTabs.tabs.find((tab) => tab.id === (activeTab ?? ownTab)) ?? visibleTabs.tabs[0]
  const filtered = useMemo(() => {
    const matching = filterDataRows(rows, columns, { search, tab: currentTab })
    return groupBy ? orderByGroup(matching, groupBy.key) : { groups: null, rows: matching }
  }, [columns, currentTab, groupBy, rows, search])
  const tableColumns = useMemo(
    () => dataColumnsToDefs(columns, renderCell, !groupBy),
    [columns, groupBy, renderCell]
  )
  const tableRows = useMemo(
    () => filtered.rows.map((values, index) => ({ id: String(index), values })),
    [filtered.rows]
  )
  const columnsByKey = useMemo(
    () => new Map(columns.map((column) => [column.key, column])),
    [columns]
  )
  const totals = useMemo(
    () => (showTotals ? dataTableTotals(columns, rows) : null),
    [columns, rows, showTotals]
  )
  const resolvedPageSize = pageSize && pageSize > 0 ? pageSize : null
  const table = useAppTable({
    columns: tableColumns,
    data: tableRows,
    enableMultiSort: false,
    initialState: {
      columnVisibility: Object.fromEntries(
        columns.filter((column) => column.hidden).map((column) => [column.key, false])
      ),
      pagination: { pageIndex: 0, pageSize: resolvedPageSize ?? (rows.length || 1) },
    },
    // Rows change on every edit in an approval table, which mustn't jump back to the first page.
    autoResetPageIndex: false,
    manualPagination: resolvedPageSize === null,
  })
  const sortedModelRows = table.getSortedRowModel().rows
  const exported = useMemo(
    () =>
      tabs || searchable
        ? dataTableExport(columns, rows)
        : dataTableExportFromRowModel(columns, sortedModelRows),
    [columns, rows, searchable, sortedModelRows, tabs]
  )
  const { setPageIndex } = table
  const currentTabId = currentTab?.id
  const { pagination, sorting } = table.state
  useEffect(() => {
    setPageIndex(0)
  }, [currentTabId, search, setPageIndex, sorting])
  const lastPageIndex = Math.max(0, Math.ceil(filtered.rows.length / pagination.pageSize) - 1)
  useEffect(() => {
    if (pagination.pageIndex > lastPageIndex) setPageIndex(lastPageIndex)
  }, [lastPageIndex, pagination.pageIndex, setPageIndex])
  const labelColumn = columns[0]
  const selectedIds = selection?.selected
  const filteredIds = useMemo(
    () => (selection ? filtered.rows.map((row) => selection.rowId(row)) : []),
    [filtered.rows, selection]
  )
  const selectedInView = filteredIds.filter((id) => selectedIds?.has(id)).length
  const visibleRowOffset =
    resolvedPageSize === null ? 0 : pagination.pageIndex * pagination.pageSize
  const visibleColumns = table.getVisibleLeafColumns()

  return (
    <table.AppTable>
      <TooltipProvider>
        <div className="grid min-w-0 gap-2">
          {visibleTabs.tabs.length > 0 || searchable ? (
            <DataTableToolbar
              activeTab={currentTab?.id}
              counts={visibleTabs.counts}
              onSearch={searchable ? setSearch : undefined}
              onTab={(id) => {
                setOwnTab(id)
                onTabChange?.(id)
              }}
              search={search}
              tabs={visibleTabs.tabs}
            />
          ) : null}
          {selection && selection.selected.size > 0 ? (
            <DataTableBulkBar
              actions={selection.actions}
              count={selection.selected.size}
              onClear={() => {
                selection.onChange(new Set())
              }}
            />
          ) : null}
          <div className="min-w-0">
            <Table
              className="table-fixed"
              style={{ minWidth: tableMinWidth(visibleColumns) + (selection ? 40 : 0) }}
            >
              <colgroup>
                {selection ? <col style={{ width: 40 }} /> : null}
                {visibleColumns.map((column) => (
                  <col key={column.id} style={{ width: column.columnDef.meta?.width }} />
                ))}
              </colgroup>
              <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {selection ? (
                      <TableHead className="w-10">
                        <Checkbox
                          aria-label="Select all rows"
                          checked={filteredIds.length > 0 && selectedInView === filteredIds.length}
                          indeterminate={selectedInView > 0 && selectedInView < filteredIds.length}
                          onCheckedChange={(checked) => {
                            const next = new Set(selection.selected)
                            for (const id of filteredIds) {
                              if (checked) next.add(id)
                              else next.delete(id)
                            }
                            selection.onChange(next)
                          }}
                        />
                      </TableHead>
                    ) : null}
                    {headerGroup.headers.map((tableHeader) => (
                      <table.AppHeader header={tableHeader} key={tableHeader.id}>
                        {() => <DataTableHeaderCell />}
                      </table.AppHeader>
                    ))}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody>
                {table.getRowModel().rows.length === 0 ? (
                  <TableRow>
                    <TableCell
                      className="text-muted-foreground py-6 text-center"
                      colSpan={visibleColumns.length + (selection ? 1 : 0)}
                    >
                      Nothing in this view.
                    </TableCell>
                  </TableRow>
                ) : null}
                {table.getRowModel().rows.flatMap((row, index, pageRows) => {
                  const values = row.original.values
                  const groupKey = groupBy?.key(values)
                  const previous = pageRows[index - 1]
                  const startsGroup =
                    groupBy !== undefined &&
                    groupKey !== undefined &&
                    (previous === undefined || groupBy.key(previous.original.values) !== groupKey)
                  const rowId = selection?.rowId(values)
                  const openRow = onRowClick ?? (rowDetails ? setSelectedRow : undefined)
                  return [
                    startsGroup ? (
                      <TableRow className="bg-muted/40 hover:bg-muted/40" key={`group:${row.id}`}>
                        <TableCell
                          className="text-sm font-medium"
                          colSpan={visibleColumns.length + (selection ? 1 : 0)}
                        >
                          {groupBy.label(groupKey, filtered.groups?.get(groupKey) ?? [])}
                        </TableCell>
                      </TableRow>
                    ) : null,
                    <TableRow
                      className={cn(openRow && "cursor-pointer", rowClassName?.(values))}
                      key={row.id}
                      {...(openRow
                        ? {
                            "aria-label": onRowClick
                              ? `Open row ${String(visibleRowOffset + index + 1)}`
                              : `Open row ${String(visibleRowOffset + index + 1)} details`,
                            onClick: () => {
                              openRow(values)
                            },
                            onKeyDown: (event: KeyboardEvent<HTMLTableRowElement>) => {
                              handleRowKeyDown(event, () => {
                                openRow(values)
                              })
                            },
                            role: "button",
                            tabIndex: 0,
                          }
                        : {})}
                    >
                      {selection && rowId !== undefined ? (
                        <TableCell className="w-10">
                          <Checkbox
                            aria-label={`Select ${labelColumn ? formatDataCell(labelColumn, values[labelColumn.key]) : "row"}`}
                            checked={selection.selected.has(rowId)}
                            onCheckedChange={(checked) => {
                              const next = new Set(selection.selected)
                              if (checked) next.add(rowId)
                              else next.delete(rowId)
                              selection.onChange(next)
                            }}
                          />
                        </TableCell>
                      ) : null}
                      {row.getVisibleCells().map((cell) => (
                        <table.AppCell cell={cell} key={cell.id}>
                          {() => <DataTableBodyCell />}
                        </table.AppCell>
                      ))}
                    </TableRow>,
                  ]
                })}
              </TableBody>
              {totals ? (
                <TableFooter>
                  <TableRow>
                    {visibleColumns.map((tableColumn, index) => {
                      const column = columnsByKey.get(tableColumn.id)
                      return (
                        <TableCell
                          className={tableColumn.columnDef.meta?.cellClassName}
                          key={tableColumn.id}
                        >
                          {index === 0 ? (
                            <span className="font-medium">Total</span>
                          ) : column === undefined || totals[column.key] === undefined ? null : (
                            <DataCell column={column} value={totals[column.key]} />
                          )}
                        </TableCell>
                      )
                    })}
                  </TableRow>
                </TableFooter>
              ) : null}
            </Table>
          </div>
          <div className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            <span>
              {String(filtered.rows.length)} {filtered.rows.length === 1 ? rowNoun[0] : rowNoun[1]}
            </span>
            {summary}
            {truncationNote ? (
              <span className="text-warning-text max-w-xl">{truncationNote}</span>
            ) : null}
            <div className="ml-auto flex shrink-0 items-center gap-1">
              <table.ViewOptions />
              <Button
                aria-label={copied ? "Copied Report Table" : "Copy Report Table"}
                onClick={() => {
                  void copy(tableToTsv(exported))
                }}
                size="icon-xs"
                type="button"
                variant="ghost"
              >
                {copied ? <CheckIcon /> : <CopyIcon />}
              </Button>
              <Button
                aria-label="Download Report CSV"
                onClick={() => {
                  downloadTableCsv(exported, exportFilename)
                }}
                size="icon-xs"
                type="button"
                variant="ghost"
              >
                <DownloadIcon />
              </Button>
            </div>
          </div>
          {resolvedPageSize !== null && filtered.rows.length > resolvedPageSize ? (
            <table.Pagination total={filtered.rows.length} />
          ) : null}
          <RowDetailSheet
            columns={columns}
            onOpenChange={(open) => {
              if (!open) {
                setSelectedRow(null)
              }
            }}
            row={selectedRow}
          />
        </div>
      </TooltipProvider>
    </table.AppTable>
  )
}

export function dataColumnsToDefs(
  columns: DataColumn[],
  renderCell?: (column: DataColumn, row: DataRow) => ReactNode | null,
  sortable = true
) {
  return columnHelper.columns(
    columns.map((column) =>
      columnHelper.accessor((row) => row.values[column.key], {
        id: column.key,
        cell: () => <DataCellFromContext column={column} renderCell={renderCell} />,
        enableHiding: true,
        enableSorting: sortable && column.kind !== "sparkline",
        header: ({ header }) => <header.ColumnHeader />,
        meta: {
          align: columnAlignment(column),
          cellClassName: columnClass(column),
          headClassName: columnClass(column),
          isMetric: column.isMetric ?? false,
          label: column.label,
          labelClassName: cn(
            "max-w-full truncate",
            columnAlignment(column) === "right" && "text-right"
          ),
          width: columnWidth(column),
        },
        sortDescFirst: sortDescFirst(column),
        sortFn: (rowA, rowB) =>
          compareDataCellValues(
            column,
            rowA.original.values[column.key],
            rowB.original.values[column.key]
          ),
        sortUndefined: "last",
      })
    )
  )
}

function DataTableHeaderCell() {
  const header = useHeaderContext()
  return header.isPlaceholder ? <TableHead /> : <header.ColumnHeader />
}

function DataTableBodyCell() {
  const cell = useCellContext()
  return (
    <TableCell className={cell.column.columnDef.meta?.cellClassName}>
      <cell.FlexRender />
    </TableCell>
  )
}

function DataCellFromContext({
  column,
  renderCell,
}: {
  column: DataColumn
  renderCell: ((column: DataColumn, row: DataRow) => ReactNode | null) | undefined
}) {
  const cell = useCellContext()
  const values = (cell.row.original as DataTableTableRow).values
  const rendered = renderCell?.(column, values)
  if (rendered !== null && rendered !== undefined) {
    return rendered
  }
  return <DataCell column={column} value={cell.getValue()} />
}

export function DataTableSkeleton({ label = "Loading report…" }: { label?: string }) {
  return (
    <div aria-busy="true" aria-label={label} className="grid gap-2">
      <Skeleton className="h-8 w-full" />
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-10 w-4/5" />
      <span className="sr-only">{label}</span>
    </div>
  )
}

function DataCell({ column, value }: { column: DataColumn; value: unknown }) {
  if (column.kind === "sparkline") {
    return <Sparkline label={column.label} values={value} />
  }
  const formatted = formatDataCell(column, value)
  if (column.kind === "status" || column.kind === "badge") {
    return (
      <Badge variant={statusVariant(formatted)}>
        {titleCaseToken(formatted.toLowerCase(), formatted)}
      </Badge>
    )
  }
  if (column.kind === "link") {
    const href = safeHttpUrl(scalarText(value))
    return href ? (
      <Tooltip>
        <TooltipTrigger
          className="text-link block min-w-0 truncate text-left underline-offset-4 hover:underline"
          render={
            <a
              aria-label={formatted}
              href={href}
              onClick={(event) => {
                event.stopPropagation()
              }}
              rel="noopener noreferrer"
              target="_blank"
            />
          }
        >
          {formatted}
          <ExternalLinkIcon className="ml-1 inline size-3" />
        </TooltipTrigger>
        <TooltipContent className="max-w-md break-all">{formatted}</TooltipContent>
      </Tooltip>
    ) : (
      <TruncatedValue align={columnAlignment(column)} value={formatted} />
    )
  }
  return <TruncatedValue align={columnAlignment(column)} value={formatted} />
}

function TruncatedValue({ align, value }: { align: "left" | "right"; value: string }) {
  return (
    <Tooltip>
      <TooltipTrigger
        className={cn("block w-full min-w-0 truncate", align === "right" && "text-right")}
        render={<span />}
      >
        {value}
      </TooltipTrigger>
      <TooltipContent className="max-w-md break-all">{value}</TooltipContent>
    </Tooltip>
  )
}

function RowDetailSheet({
  columns,
  onOpenChange,
  row,
}: {
  columns: DataColumn[]
  onOpenChange: (open: boolean) => void
  row: DataRow | null
}) {
  return (
    <Sheet onOpenChange={onOpenChange} open={row !== null}>
      <SheetContent className="sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Report row details</SheetTitle>
          <SheetDescription>All fields returned for this row.</SheetDescription>
        </SheetHeader>
        {row ? (
          <dl className="grid min-w-0 gap-3 overflow-y-auto px-4 pb-4 sm:grid-cols-2">
            {columns.map((column) => (
              <div className="min-w-0 border-b pb-2" key={column.key}>
                <dt className="text-muted-foreground text-xs">{column.label}</dt>
                <dd className="mt-1 min-w-0 text-sm wrap-break-word">
                  <DataCell column={column} value={row[column.key]} />
                </dd>
              </div>
            ))}
          </dl>
        ) : null}
      </SheetContent>
    </Sheet>
  )
}

function columnClass(column: DataColumn): string {
  return cn("min-w-0 max-w-72 overflow-hidden", columnAlignment(column) === "right" && "text-right")
}

function columnAlignment(column: DataColumn): "left" | "right" {
  if (
    column.align === "right" ||
    column.kind === "number" ||
    column.kind === "currency" ||
    column.kind === "percent"
  ) {
    return "right"
  }
  return "left"
}

function columnWidth(column: DataColumn): number | "auto" {
  if (column.width !== undefined) {
    return column.width
  }
  if (/resource_?name$/i.test(column.key)) {
    return 240
  }
  if (column.kind === "datetime") {
    return 176
  }
  if (column.kind === "text" || column.kind === "link") {
    return 176
  }
  if (column.kind === "id" || column.kind === "date" || column.kind === "status") {
    return 136
  }
  if (column.kind === "sparkline") {
    return 96
  }
  return 120
}

function tableMinWidth(columns: { columnDef: { meta?: { width?: number | "auto" } } }[]): number {
  return columns.reduce((width, column) => {
    const columnWidth = column.columnDef.meta?.width
    return width + (typeof columnWidth === "number" ? columnWidth : 120)
  }, 0)
}

function scalarText(value: unknown): string | null {
  const text = nodeText(value)
  if (text !== null) {
    return text
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value)
  }
  return null
}

function statusVariant(value: string): "success" | "warning" | "destructive" | "outline" {
  const normalized = value.trim().toLowerCase()
  if (normalized === "enabled" || normalized === "active" || normalized === "success") {
    return "success"
  }
  if (normalized === "paused" || normalized === "pending") {
    return "warning"
  }
  if (normalized === "removed" || normalized === "failed" || normalized === "error") {
    return "destructive"
  }
  return "outline"
}

export function compareDataCellValues(column: DataColumn, left: unknown, right: unknown): number {
  if (column.kind === "number" || column.kind === "currency" || column.kind === "percent") {
    const leftNumber = finiteSortNumber(left)
    const rightNumber = finiteSortNumber(right)
    if (leftNumber !== null && rightNumber !== null) {
      return leftNumber - rightNumber
    }
    if (leftNumber !== null) {
      return -1
    }
    if (rightNumber !== null) {
      return 1
    }
  }
  if (column.kind === "date" || column.kind === "datetime") {
    const leftTime = sortableTime(left, column.kind)
    const rightTime = sortableTime(right, column.kind)
    if (leftTime !== null && rightTime !== null) {
      return leftTime - rightTime
    }
    if (leftTime !== null) {
      return -1
    }
    if (rightTime !== null) {
      return 1
    }
  }
  return textCollator.compare(scalarText(left) ?? "", scalarText(right) ?? "")
}

function finiteSortNumber(value: unknown): number | null {
  const text = scalarText(value)
  if (!text?.trim()) {
    return null
  }
  const number = Number(text)
  return Number.isFinite(number) ? number : null
}

function sortableTime(value: unknown, kind: "date" | "datetime"): number | null {
  const text = scalarText(value)
  if (text === null) {
    return null
  }
  const timestamp = new Date(kind === "date" ? `${text}T00:00:00` : text).getTime()
  return Number.isNaN(timestamp) ? null : timestamp
}

function sortDescFirst(column: DataColumn): boolean {
  return (
    column.kind === "number" ||
    column.kind === "currency" ||
    column.kind === "percent" ||
    column.kind === "date" ||
    column.kind === "datetime"
  )
}

export function dataTableExportFromRowModel(
  columns: DataColumn[],
  rows: readonly { original: DataTableTableRow }[]
) {
  return dataTableExport(
    columns,
    rows.map((row) => row.original.values)
  )
}
