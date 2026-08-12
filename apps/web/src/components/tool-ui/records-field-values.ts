// apps/web/src/components/tool-ui/records-field-values.ts

import type { EditedRecords } from "@/components/tool-ui/edited-values"
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
  if (!Array.isArray(value) || (!columns && value.length === 0)) {
    return { isRecords: false, error: null }
  }
  if (columns && value.length < minRows) {
    return {
      isRecords: true,
      error: `Add at least ${String(minRows)} ${minRows === 1 ? "row" : "rows"} before approving.`,
    }
  }

  const columnsByKey = columns
    ? new Map(columns.map((column) => [column.key, column] as const))
    : null
  for (const [rowIndex, row] of value.entries()) {
    if (
      !isRecord(row) ||
      (columnsByKey &&
        (Object.keys(row).length !== columnsByKey.size ||
          Object.keys(row).some((key) => !columnsByKey.has(key))))
    ) {
      return { isRecords: false, error: null }
    }
    for (const [key, item] of Object.entries(row)) {
      if (typeof item !== "string" && !(typeof item === "number" && Number.isFinite(item))) {
        return { isRecords: false, error: null }
      }
      const column = columnsByKey?.get(key)
      if (column?.required && typeof item === "string" && !item.trim()) {
        return {
          isRecords: true,
          error: `${column.label} is required in row ${String(rowIndex + 1)}.`,
        }
      }
      if (
        column &&
        column.options.length > 0 &&
        (typeof item !== "string" || !column.options.includes(item))
      ) {
        return {
          isRecords: true,
          error: `Choose a valid ${column.label.toLocaleLowerCase()} in row ${String(rowIndex + 1)}.`,
        }
      }
    }
  }
  return { isRecords: true, error: null }
}

export function addRecordRow(value: EditedRecords, columns: ToolFieldColumn[]): EditedRecords {
  return [...value, Object.fromEntries(columns.map((column) => [column.key, ""]))]
}

export function removeRecordRow(value: EditedRecords, rowIndex: number): EditedRecords {
  return value.filter((_, index) => index !== rowIndex)
}

export function updateRecordCell(
  value: EditedRecords,
  rowIndex: number,
  columnKey: string,
  nextValue: string | number
): EditedRecords {
  return value.map((row, index) => (index === rowIndex ? { ...row, [columnKey]: nextValue } : row))
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

export function uniqueRowKeys(rows: unknown[][]): string[] {
  const occurrences = new Map<string, number>()
  return rows.map((row) => {
    const fingerprint = JSON.stringify(row)
    const occurrence = occurrences.get(fingerprint) ?? 0
    occurrences.set(fingerprint, occurrence + 1)
    return `${fingerprint}:${String(occurrence)}`
  })
}
