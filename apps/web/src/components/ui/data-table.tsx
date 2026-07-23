// apps/web/src/components/ui/data-table.tsx

import { useMemo, useState, type KeyboardEvent } from "react"
import { CheckIcon, CopyIcon, DownloadIcon, ExternalLinkIcon } from "lucide-react"

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
import { downloadTableCsv, tableToTsv } from "@/lib/table-export"
import { cn } from "@/lib/utils"

export {
  isMicrosColumnKey,
  type DataColumn,
  type DataColumnKind,
  type DataRow,
} from "@/components/ui/data-table-model"

export function DataTable({
  columns,
  exportFilename = "report.csv",
  rows,
  showTotals = false,
  truncationNote,
}: {
  columns: DataColumn[]
  exportFilename?: string
  rows: DataRow[]
  showTotals?: boolean
  truncationNote?: string | null
}) {
  const [copied, setCopied] = useState(false)
  const [selectedRow, setSelectedRow] = useState<DataRow | null>(null)
  const exported = useMemo(() => dataTableExport(columns, rows), [columns, rows])
  const totals = useMemo(
    () => (showTotals ? dataTableTotals(columns, rows) : null),
    [columns, rows, showTotals]
  )

  return (
    <div className="grid min-w-0 gap-2">
      <div className="flex items-center justify-end gap-1">
        <Button
          aria-label={copied ? "Copied Report Table" : "Copy Report Table"}
          onClick={() => {
            void copyTable(tableToTsv(exported), setCopied)
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
      <div className="border-border/70 min-w-0 overflow-hidden rounded-lg border">
        <TooltipProvider>
          <Table className="table-fixed" style={{ minWidth: tableMinWidth(columns) }}>
            <colgroup>
              {columns.map((column) => (
                <col key={column.key} style={{ width: columnWidth(column) }} />
              ))}
            </colgroup>
            <TableHeader className="bg-muted/55">
              <TableRow>
                {columns.map((column) => (
                  <TableHead className={columnClass(column)} key={column.key}>
                    <Tooltip>
                      <TooltipTrigger
                        className={cn(
                          "block w-full truncate",
                          columnAlignment(column) === "right" && "text-right"
                        )}
                        render={<span />}
                      >
                        {column.label}
                      </TooltipTrigger>
                      <TooltipContent>{column.label}</TooltipContent>
                    </Tooltip>
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row, index) => (
                <TableRow
                  aria-label={`Open row ${String(index + 1)} details`}
                  className="even:bg-muted/20 cursor-pointer"
                  key={index}
                  onClick={() => {
                    setSelectedRow(row)
                  }}
                  onKeyDown={(event) => {
                    openRowFromKeyboard(event, row, setSelectedRow)
                  }}
                  role="button"
                  tabIndex={0}
                >
                  {columns.map((column) => (
                    <TableCell className={columnClass(column)} key={column.key}>
                      <DataCell column={column} value={row[column.key]} />
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
            {totals ? (
              <TableFooter>
                <TableRow>
                  {columns.map((column, index) => (
                    <TableCell className={columnClass(column)} key={column.key}>
                      {index === 0 ? (
                        <span className="font-medium">Total</span>
                      ) : totals[column.key] === undefined ? null : (
                        <DataCell column={column} value={totals[column.key]} />
                      )}
                    </TableCell>
                  ))}
                </TableRow>
              </TableFooter>
            ) : null}
          </Table>
        </TooltipProvider>
      </div>
      <div className="text-muted-foreground flex flex-wrap items-start justify-between gap-2 text-xs">
        <span>
          {String(rows.length)} {rows.length === 1 ? "row" : "rows"}
        </span>
        {truncationNote ? (
          <span className="text-warning-foreground max-w-xl">{truncationNote}</span>
        ) : null}
      </div>
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
  )
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

function columnWidth(column: DataColumn): number {
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

function tableMinWidth(columns: DataColumn[]): number {
  return columns.reduce((width, column) => width + columnWidth(column), 0)
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

async function copyTable(value: string, onCopied: (copied: boolean) => void): Promise<void> {
  try {
    await navigator.clipboard.writeText(value)
  } catch {
    return
  }
  onCopied(true)
}
