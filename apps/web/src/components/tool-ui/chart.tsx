// apps/web/src/components/tool-ui/chart.tsx

import { useLayoutEffect, useRef, useState } from "react"
import type { ComponentProps } from "react"
import { DownloadIcon } from "lucide-react"
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { DEFAULT_CHART_COLORS, formatChartValue } from "@/components/tool-ui/chart-format"
import type { ChartSeries, ChartSpec } from "@/components/tool-ui/chart-types"
import { Button } from "@/components/ui/button"
import { downloadChartPng } from "@/lib/chart-export"

type XAxisProps = ComponentProps<typeof XAxis>
type YAxisProps = ComponentProps<typeof YAxis>
type YAxisSpec = ChartSpec["y_axes"][number]
type RenderSeries = ChartSeries & {
  stroke_dasharray: string | null
  color: string
}

export function DataChart({ spec }: { spec: ChartSpec }) {
  const chartRef = useRef<HTMLElement>(null)
  const surfaceRef = useRef<HTMLDivElement>(null)
  const [plotWidth, setPlotWidth] = useState(0)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  useLayoutEffect(() => {
    const surface = surfaceRef.current
    if (!surface) {
      return
    }
    const updateWidth = () => {
      const width = Math.max(0, Math.floor(surface.clientWidth - 16))
      setPlotWidth((current) => (current === width ? current : width))
    }
    const frame = requestAnimationFrame(updateWidth)
    const observer = new ResizeObserver(updateWidth)
    observer.observe(surface)
    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [])

  return (
    <figure aria-label={spec.title} className="grid min-w-0 gap-3" ref={chartRef}>
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 className="text-sm font-medium">{spec.title}</h4>
          {spec.subtitle ? (
            <p className="text-muted-foreground mt-0.5 text-xs">{spec.subtitle}</p>
          ) : null}
        </div>
        <Button
          disabled={exporting}
          onClick={() => {
            const chart = chartRef.current
            if (!chart) {
              return
            }
            setExporting(true)
            setExportError(null)
            void downloadChartPng(chart, {
              caption: spec.caption,
              subtitle: spec.subtitle,
              title: spec.title,
            })
              .catch((error: unknown) => {
                setExportError(
                  error instanceof Error ? error.message : "The chart could not be exported."
                )
              })
              .finally(() => {
                setExporting(false)
              })
          }}
          size="sm"
          type="button"
          variant="outline"
        >
          <DownloadIcon data-icon="inline-start" />
          {exporting ? "Exporting…" : "Download PNG"}
        </Button>
      </div>
      <div
        className="bg-card border-border/70 min-w-0 overflow-hidden rounded-lg border p-2"
        data-chart-surface
        ref={surfaceRef}
        style={{
          backgroundColor: spec.options.theme.background_color ?? undefined,
          color: spec.options.theme.text_color ?? undefined,
          height: spec.options.height,
        }}
      >
        {plotWidth > 0
          ? renderChart(spec, plotWidth, Math.max(200, spec.options.height - 18))
          : null}
      </div>
      {exportError ? (
        <p className="text-destructive text-xs" role="alert">
          {exportError}
        </p>
      ) : null}
      {spec.caption ? (
        <figcaption className="text-muted-foreground text-xs">{spec.caption}</figcaption>
      ) : null}
    </figure>
  )
}

function renderChart(spec: ChartSpec, width: number, height: number) {
  const series = renderSeries(spec)
  const common = (
    <>
      {spec.options.show_grid ? (
        <CartesianGrid
          horizontal
          stroke={spec.options.theme.grid_color ?? "var(--border)"}
          strokeOpacity={0.6}
          vertical={false}
        />
      ) : null}
      <CartesianAxes spec={spec} />
      {spec.options.show_tooltip ? <ChartTooltip series={series} spec={spec} /> : null}
      {spec.options.show_legend ? <ChartLegend spec={spec} /> : null}
    </>
  )

  if (spec.chart_type === "pie") {
    const firstSeries = series[0]
    return (
      <PieChart accessibilityLayer height={height} width={width}>
        {spec.options.show_tooltip ? <ChartTooltip series={series} spec={spec} /> : null}
        {spec.options.show_legend ? <ChartLegend spec={spec} /> : null}
        {firstSeries ? (
          <Pie
            data={pieData(spec, firstSeries)}
            dataKey={firstSeries.data_key}
            innerRadius={spec.options.donut ? "48%" : 0}
            isAnimationActive={false}
            label={spec.options.pie_labels}
            nameKey={spec.x_axis.data_key}
            outerRadius="78%"
            stroke="var(--card)"
            strokeWidth={2}
          />
        ) : null}
      </PieChart>
    )
  }

  if (spec.chart_type === "scatter") {
    return (
      <ScatterChart accessibilityLayer height={height} margin={chartMargin(spec)} width={width}>
        {common}
        {series.map((item) => (
          <Scatter
            data={scatterData(spec, item)}
            fill={item.color}
            isAnimationActive={false}
            key={item.data_key}
            name={item.label}
            yAxisId={item.y_axis_id}
          />
        ))}
      </ScatterChart>
    )
  }

  if (spec.chart_type === "line") {
    return (
      <LineChart
        accessibilityLayer
        data={spec.data}
        height={height}
        margin={chartMargin(spec)}
        width={width}
      >
        {common}
        {series.map((item) => (
          <Line
            connectNulls={item.connect_nulls}
            dataKey={item.data_key}
            dot={item.show_points ? { r: 4 } : false}
            isAnimationActive={false}
            key={item.data_key}
            name={item.label}
            stroke={item.color}
            {...(item.stroke_dasharray ? { strokeDasharray: item.stroke_dasharray } : {})}
            strokeWidth={2}
            type={item.curve}
            yAxisId={item.y_axis_id}
          />
        ))}
      </LineChart>
    )
  }

  if (spec.chart_type === "area") {
    return (
      <AreaChart
        accessibilityLayer
        data={spec.data}
        height={height}
        margin={chartMargin(spec)}
        width={width}
      >
        {common}
        {series.map((item) => (
          <Area
            connectNulls={item.connect_nulls}
            dataKey={item.data_key}
            dot={item.show_points ? { r: 4 } : false}
            fill={item.color}
            fillOpacity={0.18}
            isAnimationActive={false}
            key={item.data_key}
            name={item.label}
            {...(item.stack_id ? { stackId: item.stack_id } : {})}
            stroke={item.color}
            {...(item.stroke_dasharray ? { strokeDasharray: item.stroke_dasharray } : {})}
            strokeWidth={2}
            type={item.curve}
            yAxisId={item.y_axis_id}
          />
        ))}
      </AreaChart>
    )
  }

  if (spec.chart_type === "composed") {
    return (
      <ComposedChart
        accessibilityLayer
        data={spec.data}
        height={height}
        margin={chartMargin(spec)}
        width={width}
      >
        {common}
        {series.map((item) => (
          <ComposedSeries item={item} key={item.data_key} />
        ))}
      </ComposedChart>
    )
  }

  return (
    <BarChart
      accessibilityLayer
      data={spec.data}
      height={height}
      layout={spec.options.horizontal ? "vertical" : "horizontal"}
      margin={chartMargin(spec)}
      width={width}
    >
      {common}
      {series.map((item) => (
        <Bar
          dataKey={item.data_key}
          fill={item.color}
          isAnimationActive={false}
          key={item.data_key}
          maxBarSize={48}
          name={item.label}
          radius={spec.options.horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]}
          {...(item.stack_id ? { stackId: item.stack_id } : {})}
          {...seriesAxisProps(spec, item)}
        />
      ))}
    </BarChart>
  )
}

function ComposedSeries({ item }: { item: RenderSeries }) {
  if (item.kind === "bar") {
    return (
      <Bar
        dataKey={item.data_key}
        fill={item.color}
        isAnimationActive={false}
        maxBarSize={48}
        name={item.label}
        radius={[4, 4, 0, 0]}
        {...(item.stack_id ? { stackId: item.stack_id } : {})}
        yAxisId={item.y_axis_id}
      />
    )
  }
  if (item.kind === "area") {
    return (
      <Area
        connectNulls={item.connect_nulls}
        dataKey={item.data_key}
        dot={item.show_points ? { r: 4 } : false}
        fill={item.color}
        fillOpacity={0.18}
        isAnimationActive={false}
        name={item.label}
        {...(item.stack_id ? { stackId: item.stack_id } : {})}
        stroke={item.color}
        {...(item.stroke_dasharray ? { strokeDasharray: item.stroke_dasharray } : {})}
        strokeWidth={2}
        type={item.curve}
        yAxisId={item.y_axis_id}
      />
    )
  }
  return (
    <Line
      connectNulls={item.connect_nulls}
      dataKey={item.data_key}
      dot={item.show_points ? { r: 4 } : false}
      isAnimationActive={false}
      name={item.label}
      stroke={item.color}
      {...(item.stroke_dasharray ? { strokeDasharray: item.stroke_dasharray } : {})}
      strokeWidth={2}
      type={item.curve}
      yAxisId={item.y_axis_id}
    />
  )
}

function CartesianAxes({ spec }: { spec: ChartSpec }) {
  if (spec.options.horizontal) {
    return (
      <>
        {spec.y_axes.map((axis) => (
          <XAxis key={axis.id} {...xAxisProps(spec, axis)} />
        ))}
        <YAxis {...yAxisProps(spec)} />
      </>
    )
  }
  return (
    <>
      <XAxis {...xAxisProps(spec)} />
      {spec.y_axes.map((axis) => (
        <YAxis key={axis.id} {...yAxisProps(spec, axis)} />
      ))}
    </>
  )
}

function xAxisProps(spec: ChartSpec, valueAxis?: YAxisSpec): XAxisProps {
  if (valueAxis) {
    return {
      allowDataOverflow: false,
      allowDecimals: true,
      axisLine: axisLine(spec),
      domain: axisDomain(spec, valueAxis),
      height: valueAxis.label ? 52 : 30,
      label: axisLabel(valueAxis.label, "bottom"),
      orientation: valueAxis.orientation === "left" ? "bottom" : "top",
      tick: tickStyle(spec),
      tickFormatter: (value) =>
        formatChartValue(value, valueAxis.format, {
          currencyCode: valueAxis.currency_code,
        }),
      tickLine: axisLine(spec),
      type: "number",
      xAxisId: valueAxis.id,
    }
  }
  const scatter = spec.chart_type === "scatter"
  return {
    allowDuplicatedCategory: true,
    axisLine: axisLine(spec),
    dataKey: scatter ? "x" : spec.x_axis.data_key,
    height: spec.x_axis.label ? 52 : 30,
    interval: "preserveEnd",
    label: axisLabel(spec.x_axis.label, "bottom"),
    minTickGap: 5,
    ...(scatter ? { name: spec.x_axis.label ?? spec.x_axis.data_key } : {}),
    tick: tickStyle(spec, spec.x_axis.tick_angle),
    tickFormatter: (value) =>
      formatChartValue(value, spec.x_axis.format, {
        currencyCode: spec.x_axis.currency_code,
      }),
    tickLine: axisLine(spec),
    tickMargin: 8,
    type: scatter ? "number" : "category",
  }
}

function yAxisProps(spec: ChartSpec, valueAxis?: YAxisSpec): YAxisProps {
  if (!valueAxis) {
    return {
      allowDuplicatedCategory: true,
      axisLine: axisLine(spec),
      dataKey: spec.x_axis.data_key,
      interval: "preserveEnd",
      label: axisLabel(spec.x_axis.label, "left"),
      minTickGap: 5,
      tick: tickStyle(spec, spec.x_axis.tick_angle, "left"),
      tickFormatter: (value) =>
        formatChartValue(value, spec.x_axis.format, {
          currencyCode: spec.x_axis.currency_code,
        }),
      tickLine: axisLine(spec),
      type: "category",
      width: 96,
    }
  }
  return {
    allowDataOverflow: false,
    allowDecimals: true,
    axisLine: axisLine(spec),
    domain: axisDomain(spec, valueAxis),
    label: axisLabel(valueAxis.label, valueAxis.orientation),
    orientation: valueAxis.orientation,
    scale: valueAxis.scale,
    tick: tickStyle(spec, 0, valueAxis.orientation),
    tickFormatter: (value) =>
      formatChartValue(value, valueAxis.format, {
        currencyCode: valueAxis.currency_code,
      }),
    tickLine: axisLine(spec),
    type: "number",
    width: 64,
    yAxisId: valueAxis.id,
  }
}

function ChartTooltip({ series, spec }: { series: RenderSeries[]; spec: ChartSpec }) {
  return (
    <Tooltip
      contentStyle={{
        background: "var(--popover)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-md)",
        color: "var(--popover-foreground)",
        fontSize: 12,
      }}
      filterNull
      formatter={(value, name) => {
        const item =
          spec.chart_type === "pie"
            ? series[0]
            : series.find((candidate) => candidate.label === name || candidate.data_key === name)
        return [
          formatChartValue(value, item?.format ?? "number", {
            compact: false,
            currencyCode: item?.currency_code ?? null,
          }),
          item?.label ?? String(name),
        ]
      }}
      labelFormatter={(label) =>
        formatChartValue(label, spec.x_axis.format, {
          currencyCode: spec.x_axis.currency_code,
        })
      }
    />
  )
}

function ChartLegend({ spec }: { spec: ChartSpec }) {
  return (
    <Legend
      formatter={(value) => (
        <span
          style={{
            color: spec.options.theme.text_color ?? "var(--foreground)",
            fontSize: 12,
            marginLeft: 2,
            marginRight: 8,
          }}
        >
          {String(value)}
        </span>
      )}
      iconSize={12}
      iconType="circle"
      position="bottom"
      wrapperStyle={{ paddingTop: 10 }}
    />
  )
}

function renderSeries(spec: ChartSpec): RenderSeries[] {
  return spec.series.map((series, index) => ({
    stroke_dasharray:
      series.line_style === "dashed" ? "6 4" : series.line_style === "dotted" ? "2 3" : null,
    ...series,
    color:
      series.color ??
      spec.options.theme.palette[index % spec.options.theme.palette.length] ??
      DEFAULT_CHART_COLORS[index % DEFAULT_CHART_COLORS.length] ??
      "var(--chart-1)",
  }))
}

function scatterData(spec: ChartSpec, series: RenderSeries) {
  return spec.data.flatMap((row) => {
    const x = row[spec.x_axis.data_key]
    const y = row[series.data_key]
    return typeof x === "number" && typeof y === "number" ? [{ x, y }] : []
  })
}

function pieData(spec: ChartSpec, series: RenderSeries) {
  return spec.data.map((row, index) => ({
    ...row,
    fill:
      spec.options.theme.palette[index % spec.options.theme.palette.length] ??
      DEFAULT_CHART_COLORS[index % DEFAULT_CHART_COLORS.length] ??
      series.color,
  }))
}

function axisDomain(spec: ChartSpec, axis: YAxisSpec): [number | "auto", number | "auto"] {
  return [axis.minimum ?? (axisStartsAtZero(spec, axis) ? 0 : "auto"), axis.maximum ?? "auto"]
}

function axisStartsAtZero(spec: ChartSpec, axis: YAxisSpec) {
  if (axis.scale === "log") {
    return false
  }
  const bars = spec.series.filter(
    (series) =>
      series.y_axis_id === axis.id &&
      (spec.chart_type === "bar" || (spec.chart_type === "composed" && series.kind === "bar"))
  )
  return (
    bars.length > 0 &&
    spec.data.every((row) =>
      bars.every((series) => {
        const value = row[series.data_key]
        return typeof value !== "number" || value >= 0
      })
    )
  )
}

function axisLabel(label: string | null, position: "bottom" | "left" | "right") {
  if (!label) {
    return false
  }
  return {
    value: label,
    position:
      position === "bottom"
        ? ("insideBottom" as const)
        : position === "left"
          ? ("insideLeft" as const)
          : ("insideRight" as const),
    ...(position === "bottom" ? {} : { angle: position === "left" ? -90 : 90 }),
    offset: 0,
    style: { fill: "var(--muted-foreground)", fontSize: 11, fontWeight: 500 },
  }
}

function tickStyle(spec: ChartSpec, angle = 0, orientation?: "left" | "right") {
  return {
    fill: spec.options.theme.text_color ?? "var(--muted-foreground)",
    fontSize: 11,
    textAnchor:
      orientation === "left"
        ? ("end" as const)
        : orientation === "right"
          ? ("start" as const)
          : angle === 0
            ? ("middle" as const)
            : angle > 0
              ? ("start" as const)
              : ("end" as const),
  }
}

function axisLine(spec: ChartSpec) {
  return { stroke: spec.options.theme.grid_color ?? "var(--border)" }
}

function chartMargin(spec: ChartSpec) {
  return {
    bottom: 4,
    left: 4,
    right: spec.y_axes.some((axis) => axis.orientation === "right") ? 4 : 12,
    top: 10,
  }
}

function seriesAxisProps(spec: ChartSpec, series: RenderSeries) {
  return spec.options.horizontal ? { xAxisId: series.y_axis_id } : { yAxisId: series.y_axis_id }
}
