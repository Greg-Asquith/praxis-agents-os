import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { DataChart } from "@/components/tool-ui/chart"
import { formatChartValue } from "@/components/tool-ui/chart-format"
import type { ChartSpec } from "@/components/tool-ui/chart-types"

const SPEC: ChartSpec = {
  chart_type: "bar",
  title: "Revenue by region",
  subtitle: "Current quarter",
  caption: "Source: invoiced orders",
  x_axis: {
    data_key: "region",
    label: "Region",
    format: "text",
    currency_code: null,
    tick_angle: 0,
  },
  y_axes: [
    {
      id: "revenue",
      label: "Revenue",
      format: "currency",
      currency_code: "GBP",
      minimum: 0,
      maximum: null,
      orientation: "left",
      scale: "auto",
    },
  ],
  series: [
    {
      data_key: "revenue",
      label: "Revenue",
      kind: null,
      format: "currency",
      currency_code: "GBP",
      y_axis_id: "revenue",
      color: "#2457C5",
      stack_id: null,
      curve: "monotone",
      connect_nulls: false,
      line_style: "solid",
      show_points: false,
    },
  ],
  data: [
    { region: "North", revenue: 1250 },
    { region: "South", revenue: 2400 },
  ],
  options: {
    height: 320,
    show_grid: true,
    show_legend: true,
    show_tooltip: true,
    horizontal: false,
    donut: false,
    pie_labels: false,
    theme: {
      background_color: "#FFFFFF",
      text_color: "#172033",
      grid_color: "#D8DEE9",
      palette: [],
    },
  },
}

describe("DataChart", () => {
  it("renders a chart title, context, and PNG export action", () => {
    const html = renderToStaticMarkup(createElement(DataChart, { spec: SPEC }))

    expect(html).toContain("Revenue by region")
    expect(html).toContain("Current quarter")
    expect(html).toContain("Source: invoiced orders")
    expect(html).toContain("Download PNG")
    expect(html).toContain('aria-label="Revenue by region"')
  })

  it("formats compact, currency, percent, and date axis values", () => {
    expect(formatChartValue(12500, "number")).toMatch(/12[.,]?5K/i)
    expect(formatChartValue(1250, "currency", { currencyCode: "GBP" })).toMatch(
      /£1,250|GBP\s*1,250/
    )
    expect(formatChartValue(0.25, "percent")).toBe("25%")
    expect(formatChartValue(0.10432, "percent")).toBe("10.4%")
    expect(formatChartValue(0.10432, "percent", { compact: false })).toBe("10.43%")
    expect(formatChartValue(12500, "number", { compact: false })).toMatch(/12[,.]500/)
    expect(formatChartValue("2026-07-23", "date")).toMatch(/23.*Jul|Jul.*23/)
    expect(formatChartValue(1_700_000_000_000, "datetime")).not.toBe("1700000000000")
  })
})
