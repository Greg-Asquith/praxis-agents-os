// apps/web/tests/components/data-table/table.test.ts

import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { createAppColumnHelper, useAppTable } from "@/components/data-table/table"

type Row = { id: string; name: string }

const columnHelper = createAppColumnHelper<Row>()
const columns = columnHelper.columns([columnHelper.accessor("name", { cell: (c) => c.getValue() })])
const rows: Row[] = Array.from({ length: 12 }, (_, index) => ({
  id: String(index),
  name: `row-${String(index).padStart(2, "0")}`,
}))

function RowNames() {
  const table = useAppTable({ columns, data: rows })
  return createElement(
    "ul",
    null,
    table.getRowModel().rows.map((row) => createElement("li", { key: row.id }, row.original.name))
  )
}

describe("app table", () => {
  it("shows every row unless the table opts into client pagination", () => {
    const html = renderToStaticMarkup(createElement(RowNames))
    expect(html).toContain("row-11")
  })
})
