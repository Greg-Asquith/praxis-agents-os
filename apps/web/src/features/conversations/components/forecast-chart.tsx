// apps/web/src/features/conversations/components/forecast-chart.tsx

import { useMemo, useRef, useState } from "react"
import { DownloadIcon } from "lucide-react"
import {
  Area,
  AreaChart,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { formatChartValue } from "@/components/tool-ui/chart-format"
import { Button } from "@/components/ui/button"
import { Switch } from "@/components/ui/switch"
import type {
  ForecastCovariate,
  ForecastToolResult,
} from "@/features/conversations/native-tools/forecast-tool"
import { downloadChartPng, downloadChartSvg } from "@/lib/chart-export"
import { formatCurrency } from "@/lib/format"
import { cn } from "@/lib/utils"

type ChartRow = {
  period: string
  history: number | null
  median: number | null
  range: [number, number] | null
}

const MAIN_HEIGHT = 260
const STRIP_HEIGHT = 36
const Y_AXIS_WIDTH = 56
const MARGIN = { top: 12, right: 12, bottom: 0, left: 0 }
const ACCENT = "var(--chart-1)"
const NEUTRAL = "var(--muted-foreground)"
const CURRENCY_CODE = /^[A-Z]{3}$/

export function ForecastChart({
  result,
  useCovariates,
  onUseCovariatesChange,
}: {
  result: ForecastToolResult
  useCovariates: boolean
  onUseCovariatesChange: (value: boolean) => void
}) {
  const { chart, frequency } = result
  const figureRef = useRef<HTMLElement>(null)
  const [exportError, setExportError] = useState<string | null>(null)
  const band = useCovariates || !chart.baseline ? chart.forecast : chart.baseline
  const rows = useMemo(() => chartRows(chart.history, chart.periods, band), [band, chart])
  const holidays = useMemo(() => holidaysByPeriod(result), [result])
  const forecastStart = chart.periods[chart.history.length]
  const formatPeriod = (value: unknown) => periodLabel(value, frequency)
  const formatValue = (value: unknown, compact = true) => valueLabel(value, result.unit, compact)

  const exportChart = (format: "png" | "svg") => {
    const figure = figureRef.current
    if (!figure) {
      return
    }
    setExportError(null)
    const details = { title: result.title, subtitle: null, caption: null }
    const exported =
      format === "png"
        ? downloadChartPng(figure, details)
        : Promise.resolve().then(() => {
            downloadChartSvg(figure, details)
          })
    exported.catch((error: unknown) => {
      setExportError(error instanceof Error ? error.message : "The chart could not be exported.")
    })
  }

  return (
    <figure aria-label={`Forecast: ${result.title}`} className="grid min-w-0 gap-2" ref={figureRef}>
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
        <h4 className="min-w-0 text-sm font-medium">{result.title}</h4>
        <div className="flex gap-1">
          {(["png", "svg"] as const).map((format) => (
            <Button
              key={format}
              onClick={() => {
                exportChart(format)
              }}
              size="xs"
              type="button"
              variant="outline"
            >
              <DownloadIcon data-icon="inline-start" />
              {format.toUpperCase()}
            </Button>
          ))}
        </div>
      </div>
      <div className="min-w-0" data-chart-surface>
        <ComposedChart
          accessibilityLayer
          data={rows}
          margin={MARGIN}
          responsive
          style={{ height: MAIN_HEIGHT, width: "100%" }}
        >
          <XAxis
            axisLine={false}
            dataKey="period"
            interval="preserveStartEnd"
            minTickGap={24}
            tick={{ fill: NEUTRAL, fontSize: 11 }}
            tickFormatter={formatPeriod}
            tickLine={false}
          />
          <YAxis
            axisLine={false}
            tick={{ fill: NEUTRAL, fontSize: 11 }}
            tickFormatter={(value) => formatValue(value)}
            tickLine={false}
            width={Y_AXIS_WIDTH}
          />
          {[...holidays.keys()].map((period) => (
            <ReferenceLine
              key={period}
              stroke={NEUTRAL}
              strokeDasharray="2 3"
              strokeOpacity={0.35}
              x={period}
            />
          ))}
          {forecastStart ? (
            <ReferenceLine
              label={{
                fill: NEUTRAL,
                fontSize: 11,
                position: "insideTopLeft",
                value: "Forecast",
              }}
              stroke="var(--border)"
              strokeWidth={1.5}
              x={forecastStart}
            />
          ) : null}
          <Area
            activeDot={false}
            dataKey="range"
            fill={ACCENT}
            fillOpacity={0.18}
            isAnimationActive={false}
            name="Likely Range"
            stroke="none"
          />
          <Line
            dataKey="history"
            dot={false}
            isAnimationActive={false}
            name="History"
            stroke={NEUTRAL}
            strokeWidth={1.5}
          />
          <Line
            dataKey="median"
            dot={false}
            isAnimationActive={false}
            name="Forecast"
            stroke={ACCENT}
            strokeWidth={2}
          />
          <Tooltip
            content={({ active, label }) => {
              const row = active ? rows.find((item) => item.period === label) : undefined
              return row ? (
                <ForecastTooltip
                  formatPeriod={formatPeriod}
                  formatValue={(value) => formatValue(value, false)}
                  holidays={holidays.get(row.period) ?? []}
                  row={row}
                />
              ) : null
            }}
          />
          <Legend
            formatter={(value) => <span className="text-foreground text-xs">{String(value)}</span>}
            iconSize={10}
            iconType="circle"
            wrapperStyle={{ paddingTop: 6 }}
          />
        </ComposedChart>
      </div>
      {chart.covariates.length > 0 ? (
        <CovariateStrips
          canToggle={chart.baseline !== null}
          covariates={chart.covariates}
          forecastStart={forecastStart}
          onUseCovariatesChange={onUseCovariatesChange}
          periods={chart.periods}
          useCovariates={useCovariates}
        />
      ) : null}
      {exportError ? (
        <p className="text-destructive text-xs" role="alert">
          {exportError}
        </p>
      ) : null}
    </figure>
  )
}

function ForecastTooltip({
  formatPeriod,
  formatValue,
  holidays,
  row,
}: {
  formatPeriod: (value: unknown) => string
  formatValue: (value: unknown) => string
  holidays: string[]
  row: ChartRow
}) {
  const forecast = row.history === null && row.range !== null
  return (
    <div className="bg-popover text-popover-foreground border-border grid gap-0.5 rounded-md border px-2.5 py-1.5 text-xs shadow-sm">
      <span className="font-medium">{formatPeriod(row.period)}</span>
      {forecast && row.range ? (
        <>
          <span>Forecast: {formatValue(row.median)}</span>
          <span className="text-muted-foreground">
            Likely {formatValue(row.range[0])} to {formatValue(row.range[1])}
          </span>
        </>
      ) : (
        <span>Actual: {formatValue(row.history)}</span>
      )}
      {holidays.map((name) => (
        <span className="text-muted-foreground" key={name}>
          {name}
        </span>
      ))}
    </div>
  )
}

function CovariateStrips({
  canToggle,
  covariates,
  forecastStart,
  onUseCovariatesChange,
  periods,
  useCovariates,
}: {
  canToggle: boolean
  covariates: ForecastCovariate[]
  forecastStart: string | undefined
  onUseCovariatesChange: (value: boolean) => void
  periods: string[]
  useCovariates: boolean
}) {
  return (
    <div className="grid min-w-0 gap-1 border-t pt-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-muted-foreground text-xs font-medium">Covariates</span>
        {canToggle ? (
          <span className="flex items-center gap-2 text-xs">
            <span aria-hidden>Use in Forecast</span>
            <Switch
              aria-label="Use Covariates in Forecast"
              checked={useCovariates}
              onCheckedChange={onUseCovariatesChange}
              size="sm"
            />
          </span>
        ) : null}
      </div>
      {covariates.map((covariate) => (
        <div
          className={cn("min-w-0 transition-opacity", !useCovariates && "opacity-40")}
          key={`${covariate.source}:${covariate.name}`}
        >
          <span className="text-muted-foreground block truncate text-[11px]">{covariate.name}</span>
          <AreaChart
            data={periods.map((period, index) => ({
              period,
              value: covariate.values[index] ?? null,
            }))}
            margin={{ ...MARGIN, top: 2 }}
            responsive
            style={{ height: STRIP_HEIGHT, width: "100%" }}
          >
            <XAxis dataKey="period" hide />
            <YAxis tick={false} axisLine={false} tickLine={false} width={Y_AXIS_WIDTH} />
            {forecastStart ? <ReferenceLine stroke="var(--border)" x={forecastStart} /> : null}
            <Area
              dataKey="value"
              dot={false}
              fill={NEUTRAL}
              fillOpacity={0.2}
              isAnimationActive={false}
              stroke={NEUTRAL}
              strokeWidth={1}
              type={covariate.kind === "category" ? "stepAfter" : "monotone"}
            />
          </AreaChart>
        </div>
      ))}
    </div>
  )
}

// History, then the forecast; the forecast line and band start at the last actual value.
function chartRows(
  history: (number | null)[],
  periods: string[],
  band: ForecastToolResult["chart"]["forecast"]
): ChartRow[] {
  const last = history.length - 1
  return periods.map((period, index) => {
    if (index < history.length) {
      const value = history[index] ?? null
      const bridge = index === last && value !== null
      return {
        period,
        history: value,
        median: bridge ? value : null,
        range: bridge ? [value, value] : null,
      }
    }
    const step = index - history.length
    return {
      period,
      history: null,
      median: band.median[step] ?? null,
      range: [band.low[step] ?? 0, band.high[step] ?? 0],
    }
  })
}

// Holiday names by the forecast period that holds them, such as "Christmas Day (UK, EU)".
function holidaysByPeriod(result: ForecastToolResult): Map<string, string[]> {
  const forecastPeriods = result.chart.periods.slice(result.chart.history.length)
  const regions = new Map<string, Map<string, string[]>>()
  for (const holiday of result.holidays) {
    const period = forecastPeriods.findLast((item) => item.slice(0, 10) <= holiday.date)
    if (!period) {
      continue
    }
    const names = regions.get(period) ?? new Map<string, string[]>()
    names.set(holiday.name, [...(names.get(holiday.name) ?? []), holiday.region.toUpperCase()])
    regions.set(period, names)
  }
  return new Map(
    [...regions].map(([period, names]) => [
      period,
      [...names].map(([name, codes]) => `${name} (${[...new Set(codes)].join(", ")})`),
    ])
  )
}

function periodLabel(value: unknown, frequency: ForecastToolResult["frequency"]): string {
  if (frequency === "monthly" && typeof value === "string") {
    const [year, month] = value.split("-").map(Number)
    if (year && month) {
      return new Intl.DateTimeFormat(undefined, { month: "short", year: "numeric" }).format(
        new Date(year, month - 1, 1)
      )
    }
  }
  return formatChartValue(value, frequency === "hourly" ? "datetime" : "date")
}

function valueLabel(value: unknown, unit: string | null, compact: boolean): string {
  if (typeof value === "number" && unit && CURRENCY_CODE.test(unit)) {
    return formatCurrency(value, unit, {
      maximumFractionDigits: compact ? 1 : 2,
      ...(compact ? { notation: "compact" as const } : {}),
    })
  }
  const text = formatChartValue(value, "number", { compact })
  return unit && !compact && typeof value === "number" ? `${text} ${unit}` : text
}
