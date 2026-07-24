// apps/web/src/components/ui/data-table-model.ts

import { nodeText } from "@/components/tool-ui/untrusted-node"
import { formatCurrency, formatDateTime } from "@/lib/format"
import type { ExportTable } from "@/lib/table-export"

export type DataColumnKind =
  | "text"
  | "number"
  | "currency"
  | "percent"
  | "date"
  | "datetime"
  | "status"
  | "badge"
  | "link"
  | "id"

export type DataColumn = {
  align?: "left" | "right"
  currencyCode?: string
  isMetric?: boolean
  key: string
  kind: DataColumnKind
  label: string
  unit?: "micros"
}

export type DataRow = Record<string, unknown>

export function formatDataCell(column: DataColumn, value: unknown): string {
  const text = scalarText(value)
  if (text === null) {
    return "—"
  }
  if (column.kind === "currency") {
    const numeric = finiteNumber(text)
    if (numeric === null) {
      return text
    }
    const amount =
      column.unit === "micros" || isMicrosColumnKey(column.key) ? numeric / 1_000_000 : numeric
    return formatCurrency(amount, column.currencyCode ?? null, {
      fallbackMaximumFractionDigits: 6,
    })
  }
  if (column.kind === "percent") {
    const numeric = finiteNumber(text)
    if (numeric === null) {
      return text
    }
    const percent = Math.abs(numeric) <= 1 ? numeric : numeric / 100
    return new Intl.NumberFormat(undefined, {
      maximumFractionDigits: 2,
      style: "percent",
    }).format(percent)
  }
  if (column.kind === "number") {
    const numeric = finiteNumber(text)
    return numeric === null ? text : new Intl.NumberFormat().format(numeric)
  }
  if (column.kind === "date") {
    const date = new Date(`${text}T00:00:00`)
    return Number.isNaN(date.getTime())
      ? text
      : new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date)
  }
  if (column.kind === "datetime") {
    const date = new Date(text)
    return Number.isNaN(date.getTime()) ? text : formatDateTime(text)
  }
  return text
}

export function isMicrosColumnKey(key: string): boolean {
  return /micros$/i.test(key)
}

export function dataTableExport(columns: DataColumn[], rows: DataRow[]): ExportTable {
  return {
    headers: columns.map((column) => column.label),
    rows: rows.map((row) => columns.map((column) => exportCell(row[column.key]))),
  }
}

export function dataTableTotals(
  columns: DataColumn[],
  rows: DataRow[]
): Record<string, number> | null {
  const totals: Record<string, number> = {}
  for (const column of columns) {
    if (!column.isMetric) {
      continue
    }
    let found = false
    let total = 0
    for (const row of rows) {
      const numeric = finiteNumber(scalarText(row[column.key]))
      if (numeric !== null) {
        found = true
        total += numeric
      }
    }
    if (found) {
      totals[column.key] = total
    }
  }
  return Object.keys(totals).length > 0 ? totals : null
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

function exportCell(value: unknown): string {
  const scalar = scalarText(value)
  if (scalar !== null) {
    return scalar
  }
  if (value === null || value === undefined) {
    return ""
  }
  try {
    return JSON.stringify(value)
  } catch {
    return ""
  }
}

function finiteNumber(value: string | null): number | null {
  if (!value?.trim()) {
    return null
  }
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}
