import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { DataTable, type DataColumn } from "@/components/ui/data-table"
import { dataTableExport, dataTableTotals, formatDataCell } from "@/components/ui/data-table-model"
import { tableToCsv } from "@/lib/table-export"

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
const DATE_COLUMN: DataColumn = { key: "segments.date", kind: "date", label: "Date" }
const STATUS_COLUMN: DataColumn = {
  key: "campaign.status",
  kind: "status",
  label: "Status",
}
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
    expect(html).toContain("Open row 1 details")
    expect(html).toContain("Report limited to 1 row.")
    expect(html).toContain("Total")
    expect(html).toContain("12.5%")
    expect(html).toContain("Enabled")
    expect(html).toContain("table-fixed")
    expect(html).toContain("<colgroup>")
    expect(html).toContain("truncate")
    expect(html).toContain("text-right")
    expect(html).not.toContain("<code")
  })
})
