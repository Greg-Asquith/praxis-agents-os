// apps/web/tests/components/data-table/filter.test.ts

import { describe, expect, it } from "vitest"

import { filterDataRows, orderByGroup, tabCounts } from "@/components/data-table/filter"
import type { DataColumn, DataRow } from "@/components/ui/data-table"

const columns: DataColumn[] = [
  { key: "item", kind: "text", label: "Item" },
  { key: "campaign", kind: "text", label: "Campaign" },
]
const rows: DataRow[] = [
  { item: "Brand", campaign: "Summer", on: true },
  { item: "Trail Shoes", campaign: "Winter", on: false },
  { item: "Trail Socks", campaign: "Summer", on: true },
]
const tabs = [
  { id: "all", label: "All", match: () => true },
  { id: "on", label: "On", match: (row: DataRow) => row["on"] === true },
]

describe("data table filtering", () => {
  it("requires every search word and the active tab, across all columns", () => {
    expect(filterDataRows(rows, columns, { search: "trail summer", tab: undefined })).toEqual([
      rows[2],
    ])
    expect(filterDataRows(rows, columns, { search: "trail", tab: tabs[1] })).toEqual([rows[2]])
    expect(tabCounts(rows, tabs).get("on")).toBe(2)
  })

  it("gathers rows by group in order of first appearance", () => {
    const grouped = orderByGroup(rows, (row) => String(row["campaign"]))
    expect(grouped.rows.map((row) => row["item"])).toEqual(["Brand", "Trail Socks", "Trail Shoes"])
    expect([...grouped.groups.keys()]).toEqual(["Summer", "Winter"])
  })
})
