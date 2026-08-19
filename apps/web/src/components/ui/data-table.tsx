// apps/web/src/components/ui/data-table.tsx

import { useMemo, useState, type KeyboardEvent, type ReactNode } from "react"
import { CheckIcon, CopyIcon, DownloadIcon, ExternalLinkIcon } from "lucide-react"

import {
  createAppColumnHelper,
  useAppTable,
  useCellContext,
  useHeaderContext,
} from "@/components/data-table/table"
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
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
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
const textCollator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" })

export function DataTable({
  columns,
  exportFilename = "report.csv",
  header,
  pageSize,
  rows,
  showTotals = false,
  truncationNote,
}: {
  columns: DataColumn[]
  exportFilename?: string
  header?: ReactNode
  pageSize?: number
  rows: DataRow[]
  showTotals?: boolean
  truncationNote?: string | null
}) {
  const { copied, copy } = useClipboardCopy()
  const [selectedRow, setSelectedRow] = useState<DataRow | null>(null)
  const tableColumns = useMemo(() => dataColumnsToDefs(columns), [columns])
  const tableRows = useMemo(
    () => rows.map((values, index) => ({ id: String(index), values })),
    [rows]
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
      pagination: { pageIndex: 0, pageSize: resolvedPageSize ?? (rows.length || 1) },
    },
    manualPagination: resolvedPageSize === null,
  })
  const sortedModelRows = table.getSortedRowModel().rows
  const exported = useMemo(
    () => dataTableExportFromRowModel(columns, sortedModelRows),
    [columns, sortedModelRows]
  )
  const pagination = table.state.pagination
  const visibleRowOffset =
    resolvedPageSize === null ? 0 : pagination.pageIndex * pagination.pageSize
  const visibleColumns = table.getVisibleLeafColumns()

  return (
    <table.AppTable>
      <TooltipProvider>
        <div className="grid min-w-0 gap-2">
          <div className={cn("flex gap-3", header ? "items-end justify-between" : "justify-end")}>
            {header ? <div className="min-w-0 flex-1">{header}</div> : null}
            <div className="flex shrink-0 items-center gap-1">
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
          <div className="min-w-0">
            <Table className="table-fixed" style={{ minWidth: tableMinWidth(visibleColumns) }}>
              <colgroup>
                {visibleColumns.map((column) => (
                  <col key={column.id} style={{ width: column.columnDef.meta?.width }} />
                ))}
              </colgroup>
              <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((tableHeader) => (
                      <table.AppHeader header={tableHeader} key={tableHeader.id}>
                        {() => <DataTableHeaderCell />}
                      </table.AppHeader>
                    ))}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody>
                {table.getRowModel().rows.map((row, index) => (
                  <TableRow
                    aria-label={`Open row ${String(visibleRowOffset + index + 1)} details`}
                    className="cursor-pointer"
                    key={row.id}
                    onClick={() => {
                      setSelectedRow(row.original.values)
                    }}
                    onKeyDown={(event) => {
                      openRowFromKeyboard(event, row.original.values, setSelectedRow)
                    }}
                    role="button"
                    tabIndex={0}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <table.AppCell cell={cell} key={cell.id}>
                        {() => <DataTableBodyCell />}
                      </table.AppCell>
                    ))}
                  </TableRow>
                ))}
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
          <div className="text-muted-foreground flex flex-wrap items-start justify-between gap-2 text-xs">
            <span>
              {String(rows.length)} {rows.length === 1 ? "row" : "rows"}
            </span>
            {truncationNote ? (
              <span className="text-warning-foreground max-w-xl">{truncationNote}</span>
            ) : null}
          </div>
          {resolvedPageSize !== null && rows.length > resolvedPageSize ? (
            <table.Pagination total={rows.length} />
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

export function dataColumnsToDefs(columns: DataColumn[]) {
  return columnHelper.columns(
    columns.map((column) =>
      columnHelper.accessor((row) => row.values[column.key], {
        id: column.key,
        cell: () => <DataCellFromContext column={column} />,
        enableHiding: true,
        enableSorting: true,
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

function DataCellFromContext({ column }: { column: DataColumn }) {
  const cell = useCellContext()
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

function openRowFromKeyboard(
  event: KeyboardEvent<HTMLTableRowElement>,
  row: DataRow,
  select: (row: DataRow) => void
) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault()
    select(row)
  }
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
