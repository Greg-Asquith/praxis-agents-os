// apps/web/src/components/tool-ui/use-chart-export.ts

import { useState } from "react"
import type { RefObject } from "react"

import { downloadChartPng, downloadChartSvg } from "@/lib/chart-export"

type ChartExportDetails = Parameters<typeof downloadChartPng>[1]

export function useChartExport(
  chartRef: RefObject<HTMLElement | null>,
  details: ChartExportDetails
) {
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  const exportChart = (format: "png" | "svg") => {
    const chart = chartRef.current
    if (!chart) {
      return
    }
    setExporting(true)
    setExportError(null)
    const exported =
      format === "png"
        ? downloadChartPng(chart, details)
        : Promise.resolve().then(() => {
            downloadChartSvg(chart, details)
          })
    void exported
      .catch((error: unknown) => {
        setExportError(error instanceof Error ? error.message : "The chart could not be exported.")
      })
      .finally(() => {
        setExporting(false)
      })
  }

  return { exportChart, exportError, exporting }
}
