// apps/web/src/components/tool-ui/records-field-values.ts

import type { EditedRecordCell, EditedRecords } from "@/components/tool-ui/edited-values"
import type { ToolFieldColumn } from "@/components/tool-ui/field-resolution"
import { isRecord } from "@/lib/guards"

export type KeyedRecordRow = {
  key: string
  row: EditedRecords[number]
  rowIndex: number
}

export type RecordRowsValidity =
  { isRecords: false; error: null } | { isRecords: true; error: string | null }

export function recordRowsValidity(
  value: unknown,
  columns?: ToolFieldColumn[],
  minRows = 0
): RecordRowsValidity {
  const shape = recordRowsShape(value, columns, minRows)
  if (shape !== null) return shape
  if (!Array.isArray(value)) return { isRecords: false, error: null }

  const columnsByKey = columns
    ? new Map(columns.map((column) => [column.key, column] as const))
    : null
  for (const [rowIndex, row] of value.entries()) {
    const validity = recordRowValidity(row, rowIndex, columns, columnsByKey)
    if (validity.error !== null || !validity.isRecords) return validity
  }
  return { isRecords: true, error: null }
}

function recordRowsShape(
  value: unknown,
  columns: ToolFieldColumn[] | undefined,
  minRows: number
): RecordRowsValidity | null {
  if (!Array.isArray(value)) return { isRecords: false, error: null }
  if (!columns && value.length === 0) return { isRecords: false, error: null }
  if (!columns || value.length >= minRows) return null
  return {
    isRecords: true,
    error: `Add at least ${String(minRows)} ${minRows === 1 ? "row" : "rows"} before approving.`,
  }
}

function recordRowValidity(
  row: unknown,
  rowIndex: number,
  columns: ToolFieldColumn[] | undefined,
  columnsByKey: Map<string, ToolFieldColumn> | null
): RecordRowsValidity {
  if (!isRecord(row)) return { isRecords: false, error: null }
  if (columnsByKey && Object.keys(row).some((key) => !columnsByKey.has(key))) {
    return { isRecords: false, error: null }
  }
  const missing = columns?.find((column) => column.required && !Object.hasOwn(row, column.key))
  if (missing) {
    return {
      isRecords: true,
      error: `${missing.label} is required in row ${String(rowIndex + 1)}.`,
    }
  }
  for (const [key, item] of Object.entries(row)) {
    const error = recordCellError(item, columnsByKey?.get(key), rowIndex)
    if (error === false) return { isRecords: false, error: null }
    if (error) return { isRecords: true, error }
  }
  return { isRecords: true, error: null }
}

export function addRecordRow(value: EditedRecords, columns: ToolFieldColumn[]): EditedRecords {
  const rowEntries = columns.flatMap((column): [string, EditedRecordCell][] => {
    if (column.default_value !== undefined && column.default_value !== null) {
      return [[column.key, column.default_value]]
    }
    if (column.format === "list") return [[column.key, []]]
    if (column.format === "keyvalue") return [[column.key, {}]]
    return column.required ? [[column.key, ""]] : []
  })
  return [...value, Object.fromEntries(rowEntries)]
}

function recordCellError(
  item: unknown,
  column: ToolFieldColumn | undefined,
  rowIndex: number
): string | false | null {
  if (!validRecordCell(item, column?.format ?? "text")) return false
  if (!column) return null
  if (requiredCellIsEmpty(item, column)) {
    return `${column.label} is required in row ${String(rowIndex + 1)}.`
  }
  if (column.options.length > 0 && !column.options.includes(String(item))) {
    return `Choose a valid ${column.label.toLocaleLowerCase()} in row ${String(rowIndex + 1)}.`
  }
  if (exceedsEntryLimit(item, column)) {
    return `${column.label} can contain at most ${String(column.max_entries)} entries in row ${String(rowIndex + 1)}.`
  }
  return null
}

function requiredCellIsEmpty(item: unknown, column: ToolFieldColumn): boolean {
  if (!column.required) return false
  if (typeof item === "string") return !item.trim()
  if (Array.isArray(item)) return item.length === 0
  return isRecord(item) && Object.keys(item).length === 0
}

function exceedsEntryLimit(item: unknown, column: ToolFieldColumn): boolean {
  if (column.max_entries === undefined || column.max_entries === null) return false
  return isRecord(item) && Object.keys(item).length > column.max_entries
}

export function removeRecordRow(value: EditedRecords, rowIndex: number): EditedRecords {
  return value.filter((_, index) => index !== rowIndex)
}

export function updateRecordCell(
  value: EditedRecords,
  rowIndex: number,
  columnKey: string,
  nextValue: EditedRecordCell
): EditedRecords {
  return value.map((row, index) => (index === rowIndex ? { ...row, [columnKey]: nextValue } : row))
}

function validRecordCell(value: unknown, format: NonNullable<ToolFieldColumn["format"]>): boolean {
  if (format === "list")
    return Array.isArray(value) && value.every((item) => typeof item === "string")
  if (format === "keyvalue") {
    return (
      isRecord(value) &&
      Object.values(value).every(
        (item) =>
          typeof item === "string" ||
          typeof item === "boolean" ||
          (typeof item === "number" && Number.isFinite(item))
      )
    )
  }
  return typeof value === "string" || (typeof value === "number" && Number.isFinite(value))
}

export function normalizeRecordNumericInput(value: string): number | null {
  if (value.trim() === "") {
    return null
  }
  const normalized = Number(value)
  return Number.isFinite(normalized) ? normalized : null
}

export function keyedRecordRows(value: EditedRecords, rowKeys: string[]): KeyedRecordRow[] {
  return value.map((row, rowIndex) => ({
    key: rowKeys[rowIndex] ?? `record-row-${String(rowIndex)}`,
    row,
    rowIndex,
  }))
}

export function configuredRecordCellCount(
  row: EditedRecords[number],
  columns: ToolFieldColumn[]
): number {
  return columns.filter((column) => hasConfiguredRecordCell(row[column.key])).length
}

export function toggleRecordRowExpansion(current: Set<string>, rowKey: string): Set<string> {
  const next = new Set(current)
  if (next.has(rowKey)) next.delete(rowKey)
  else next.add(rowKey)
  return next
}

function hasConfiguredRecordCell(value: EditedRecordCell | undefined): boolean {
  if (typeof value === "string") return value.trim().length > 0
  if (typeof value === "number") return Number.isFinite(value)
  if (Array.isArray(value)) return value.length > 0
  return isRecord(value) && Object.keys(value).length > 0
}

export function uniqueRowKeys(rows: unknown[][]): string[] {
  const occurrences = new Map<string, number>()
  return rows.map((row) => {
    const fingerprint = JSON.stringify(row)
    const occurrence = occurrences.get(fingerprint) ?? 0
    occurrences.set(fingerprint, occurrence + 1)
    return `${fingerprint}:${String(occurrence)}`
  })
}
