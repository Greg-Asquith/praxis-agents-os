// apps/web/src/components/tool-ui/records-field-values.ts

import type { EditedRecords } from "@/components/tool-ui/edited-values"
import type { ToolFieldColumn } from "@/components/tool-ui/field-resolution"

export type KeyedRecordRow = {
  key: string
  row: EditedRecords[number]
  rowIndex: number
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
