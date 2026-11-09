// apps/web/src/components/data-table/filter.ts

import type { ReactNode } from "react"

import { formatDataCell, type DataColumn, type DataRow } from "@/components/ui/data-table-model"

export type DataTableTab = {
  id: string
  label: string
  match: (row: DataRow) => boolean
  // Drops the tab while no row matches, such as Needs Attention.
  hideWhenEmpty?: boolean
}

export type DataTableGroup = {
  key: (row: DataRow) => string
  label: (key: string, rows: readonly DataRow[]) => ReactNode
}

export function tabCounts(rows: readonly DataRow[], tabs: readonly DataTableTab[]) {
  return new Map(tabs.map((tab) => [tab.id, rows.filter(tab.match).length]))
}

/** Rows matching the active tab and every word of the search, in their given order. */
export function filterDataRows(
  rows: readonly DataRow[],
  columns: readonly DataColumn[],
  { search, tab }: { search: string; tab: DataTableTab | undefined }
): DataRow[] {
  const words = search.toLowerCase().split(/\s+/).filter(Boolean)
  return rows.filter((row) => {
    if (tab && !tab.match(row)) return false
    if (words.length === 0) return true
    const text = columns
      .map((column) => formatDataCell(column, row[column.key]))
      .join(" ")
      .toLowerCase()
    return words.every((word) => text.includes(word))
  })
}

/** Rows gathered by group, groups in order of first appearance. */
export function orderByGroup(rows: readonly DataRow[], key: DataTableGroup["key"]) {
  const groups = new Map<string, DataRow[]>()
  for (const row of rows) {
    const groupKey = key(row)
    const members = groups.get(groupKey)
    if (members) members.push(row)
    else groups.set(groupKey, [row])
  }
  return { groups, rows: [...groups.values()].flat() }
}
