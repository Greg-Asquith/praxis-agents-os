import { describe, expect, it } from "vitest"

import { chartPngFilename } from "@/lib/chart-export"

describe("chartPngFilename", () => {
  it("creates a portable PNG filename from the chart title", () => {
    expect(chartPngFilename(" Revenue by Region — Q3 ")).toBe("revenue-by-region-q3.png")
    expect(chartPngFilename("!!!")).toBe("chart.png")
  })
})
