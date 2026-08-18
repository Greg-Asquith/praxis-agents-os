import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import {
  compareDataCellValues,
  DataTable,
  dataColumnsToDefs,
  dataTableExportFromRowModel,
  type DataColumn,
  type DataRow,
} from "@/components/ui/data-table"
import { useAppTable } from "@/components/data-table/table"
import { dataTableExport, dataTableTotals, formatDataCell } from "@/components/ui/data-table-model"
import { tableToCsv, tableToTsv } from "@/lib/table-export"

const NODE = (content: string) => ({
  node: "praxis_untrusted" as const,
  source_kind: "google_ads_report",
  source_ref: "123",
  content,
})

const ID_COLUMN: DataColumn = { key: "campaign.id", kind: "id", label: "Campaign ID" }
const COST_COLUMN: DataColumn = {
  key: "metrics.cost_micros",
  kind: "currency",
  label: "Cost",
  currencyCode: "GBP",
  isMetric: true,
}
const MICROS_COLUMN: DataColumn = {
  key: "metrics.cost_micros",
  kind: "currency",
  label: "Cost",
  isMetric: true,
}
const CAMEL_CASE_MICROS_COLUMN: DataColumn = {
  key: "metrics.costMicros",
  kind: "currency",
  label: "Cost",
  currencyCode: "GBP",
  isMetric: true,
}
const IMPLICIT_MICROS_COLUMN: DataColumn = {
  key: "metrics.averageCpc",
  kind: "currency",
  label: "Average CPC",
  currencyCode: "GBP",
  isMetric: true,
  unit: "micros",
}
const CTR_COLUMN: DataColumn = {
  key: "metrics.ctr",
  kind: "percent",
  label: "CTR",
  isMetric: true,
}
const CLICKS_COLUMN: DataColumn = {
  key: "metrics.clicks",
  kind: "number",
  label: "Clicks",
  isMetric: true,
}
const DURATION_COLUMN: DataColumn = {
  key: "averageSessionDuration",
  kind: "number",
  label: "Average session duration",
  isMetric: true,
  unit: "seconds",
}
const DATE_COLUMN: DataColumn = { key: "segments.date", kind: "date", label: "Date" }
const STATUS_COLUMN: DataColumn = {
  key: "campaign.status",
  kind: "status",
  label: "Status",
}
const LINK_COLUMN: DataColumn = { key: "landing_page", kind: "link", label: "Landing page" }
const COLUMNS = [ID_COLUMN, COST_COLUMN, CTR_COLUMN, DATE_COLUMN, STATUS_COLUMN]

describe("DataTable", () => {
  it("formats numbers, percentages, dates, and converted micros", () => {
    expect(formatDataCell(COST_COLUMN, NODE("1250000"))).toMatch(/£1\.25|GBP\s*1\.25/)
    expect(formatDataCell(CAMEL_CASE_MICROS_COLUMN, NODE("120067374"))).toMatch(
      /£120\.07|GBP\s*120\.07/
    )
    expect(formatDataCell(IMPLICIT_MICROS_COLUMN, NODE("73040000"))).toMatch(/£73\.04|GBP\s*73\.04/)
    expect(formatDataCell(MICROS_COLUMN, NODE("1"))).toMatch(/0[.,]000001/)
    expect(formatDataCell(MICROS_COLUMN, NODE("-750000"))).toMatch(/-0[.,]75/)
    expect(formatDataCell(CTR_COLUMN, NODE("0.125"))).toBe("12.5%")
    expect(formatDataCell(DATE_COLUMN, NODE("2026-07-23"))).toContain("2026")
    expect(formatDataCell(ID_COLUMN, NODE("987654"))).toBe("987654")
    expect(formatDataCell(DURATION_COLUMN, 92)).toBe("1 min 32 sec")
  })

  it("sums opted-in metric columns using raw report values", () => {
    const totals = dataTableTotals(COLUMNS, [
      { "metrics.cost_micros": NODE("1250000"), "metrics.ctr": NODE("0.1") },
      { "metrics.cost_micros": NODE("750000"), "metrics.ctr": NODE("0.2") },
    ])
    expect(totals?.["metrics.cost_micros"]).toBe(2_000_000)
    expect(totals?.["metrics.ctr"]).toBeCloseTo(0.3)
  })

  it("exports node content without frame markers or node JSON", () => {
    const exported = dataTableExport(COLUMNS, [
      {
        "campaign.id": NODE("987654"),
        "metrics.cost_micros": NODE("1250000"),
        "metrics.ctr": NODE("0.125"),
        "segments.date": NODE("2026-07-23"),
        "campaign.status": NODE("ENABLED"),
      },
    ])
    const csv = tableToCsv(exported)

    expect(csv).toContain("987654")
    expect(csv).toContain("1250000")
    expect(csv).not.toContain("praxis_untrusted")
    expect(csv).not.toContain("PRAXIS_UNTRUSTED_CONTENT")
    expect(csv).not.toContain("source_kind")
  })

  it("sorts report values by kind and exports the full sorted row model", () => {
    const rows: DataRow[] = Array.from({ length: 30 }, (_, index) => ({
      "campaign.id": NODE(`campaign-${String(index + 1).padStart(2, "0")}`),
      "metrics.cost_micros": NODE(String((index + 1) * 1_000_000)),
    }))
    const html = renderToStaticMarkup(
      createElement(SortedExport, {
        columns: [ID_COLUMN, COST_COLUMN],
        rows,
        sortColumn: COST_COLUMN.key,
      })
    )

    expect(html.indexOf("campaign-30")).toBeLessThan(html.indexOf("campaign-01"))
    expect(html).toContain("campaign-16")
    expect(html).not.toContain("praxis_untrusted")
  })

  it("uses numeric, date, and natural text comparators", () => {
    expect(compareDataCellValues(COST_COLUMN, NODE("2"), NODE("10"))).toBeLessThan(0)
    expect(compareDataCellValues(DATE_COLUMN, NODE("2026-07-23"), NODE("2026-08-01"))).toBeLessThan(
      0
    )
    expect(compareDataCellValues(ID_COLUMN, NODE("campaign-2"), NODE("campaign-10"))).toBeLessThan(
      0
    )
    expect(compareDataCellValues(DURATION_COLUMN, 92, 120)).toBeLessThan(0)
    expect(dataTableExport([DURATION_COLUMN], [{ averageSessionDuration: 92 }]).rows).toEqual([
      ["92"],
    ])
  })

  it("renders totals, export actions, truncation context, and row-detail affordances", () => {
    const html = renderToStaticMarkup(
      createElement(DataTable, {
        columns: COLUMNS,
        rows: [
          {
            "campaign.id": NODE("987654"),
            "metrics.cost_micros": NODE("1250000"),
            "metrics.ctr": NODE("0.125"),
            "segments.date": NODE("2026-07-23"),
            "campaign.status": NODE("ENABLED"),
          },
        ],
        showTotals: true,
        truncationNote: "Report limited to 1 row.",
      })
    )

    expect(html).toContain("Copy Report Table")
    expect(html).toContain("Download Report CSV")
    expect(html).toContain("Choose report columns")
    expect(html).toContain("Open row 1 details")
    expect(html).toContain("Report limited to 1 row.")
    expect(html).toContain("Total")
    expect(html).toContain("12.5%")
    expect(html).toContain("Enabled")
    expect(html).toContain("table-fixed")
    expect(html).toContain("<colgroup>")
    expect(html).toContain("truncate")
    expect(html).toContain("text-right")
    expect(html).toContain('aria-sort="none"')
    expect(html).not.toContain("<code")
  })

  it("renders only validated HTTP links as external anchors", () => {
    const html = renderToStaticMarkup(
      createElement(DataTable, {
        columns: [LINK_COLUMN],
        rows: [
          { landing_page: NODE("https://example.com/landing") },
          { landing_page: NODE("javascript:alert(1)") },
        ],
      })
    )

    expect(html).toContain('href="https://example.com/landing"')
    expect(html).toContain('rel="noopener noreferrer"')
    expect(html).toContain('target="_blank"')
    expect(html).not.toContain('href="javascript:alert(1)"')
    expect(html).toContain("javascript:alert(1)")
  })

  it("paginates large row sets while exporting the complete table", () => {
    const rows = Array.from({ length: 30 }, (_, index) => ({
      "campaign.id": `campaign-${String(index + 1).padStart(2, "0")}`,
    }))
    const html = renderToStaticMarkup(
      createElement(DataTable, {
        columns: [ID_COLUMN],
        pageSize: 25,
        rows,
      })
    )
    const exported = dataTableExport([ID_COLUMN], rows)

    expect(html).toContain("campaign-01")
    expect(html).toContain("campaign-25")
    expect(html).not.toContain("campaign-26")
    expect(html).toContain("Showing 1-25 of 30")
    expect(html).toContain("Previous")
    expect(html).toContain("Next")
    expect(exported.rows).toHaveLength(30)
    expect(exported.rows.at(-1)).toEqual(["campaign-30"])
  })

  it("keeps totals over all rows when the visible table is paginated", () => {
    const rows = Array.from({ length: 30 }, (_, index) => ({
      "campaign.id": `campaign-${String(index + 1).padStart(2, "0")}`,
      "metrics.clicks": String(index + 1),
    }))
    const html = renderToStaticMarkup(
      createElement(DataTable, {
        columns: [ID_COLUMN, CLICKS_COLUMN],
        pageSize: 25,
        rows,
        showTotals: true,
      })
    )

    expect(html).not.toContain("campaign-26")
    expect(html).toContain("Total")
    expect(html).toContain(">465<")
  })
})

function SortedExport({
  columns,
  rows,
  sortColumn,
}: {
  columns: DataColumn[]
  rows: DataRow[]
  sortColumn: string
}) {
  const table = useAppTable({
    columns: dataColumnsToDefs(columns),
    data: rows.map((values, index) => ({ id: String(index), values })),
    manualPagination: true,
    state: { sorting: [{ desc: true, id: sortColumn }] },
  })
  const exported = dataTableExportFromRowModel(columns, table.getSortedRowModel().rows)

  return createElement("pre", null, tableToTsv(exported))
}
