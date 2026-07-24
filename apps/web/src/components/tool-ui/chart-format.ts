// apps/web/src/components/tool-ui/chart-format.ts

import type { ChartValueFormat } from "@/components/tool-ui/chart-types"
import { formatCurrency } from "@/lib/format"

export const DEFAULT_CHART_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
] as const

export function formatChartValue(
  value: unknown,
  format: ChartValueFormat,
  { compact = true, currencyCode = null }: { compact?: boolean; currencyCode?: string | null } = {}
): string {
  if (format === "date" || format === "datetime") {
    const date = chartDate(value)
    if (!Number.isNaN(date.getTime())) {
      return new Intl.DateTimeFormat(undefined, {
        day: "numeric",
        month: "short",
        ...(format === "datetime" ? { hour: "numeric", minute: "2-digit" } : {}),
      }).format(date)
    }
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    if (format === "currency") {
      return formatCurrency(value, currencyCode)
    }
    if (format === "percent") {
      // Percent values are fractions (0.125 renders as 12.5%), matching provider metrics.
      return new Intl.NumberFormat(undefined, {
        maximumFractionDigits: compact ? 1 : 2,
        style: "percent",
      }).format(value)
    }
    return new Intl.NumberFormat(undefined, {
      maximumFractionDigits: 2,
      ...(compact ? { notation: "compact" as const } : {}),
    }).format(value)
  }
  return typeof value === "string" || typeof value === "boolean" ? String(value) : "—"
}

function chartDate(value: unknown): Date {
  if (typeof value === "number") {
    return new Date(value)
  }
  if (typeof value === "string") {
    const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
    if (dateOnly) {
      return new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]))
    }
    return new Date(value)
  }
  return new Date(Number.NaN)
}
