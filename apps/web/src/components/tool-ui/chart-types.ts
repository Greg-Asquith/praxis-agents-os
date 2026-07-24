// apps/web/src/components/tool-ui/chart-types.ts

export type ChartValueFormat = "text" | "number" | "currency" | "percent" | "date" | "datetime"
type ChartCurve = "linear" | "monotone" | "step"

export type ChartSeries = {
  color: string | null
  connect_nulls: boolean
  currency_code: string | null
  curve: ChartCurve
  data_key: string
  format: "number" | "currency" | "percent"
  kind: "line" | "bar" | "area" | null
  label: string
  line_style: "solid" | "dashed" | "dotted"
  show_points: boolean
  stack_id: string | null
  y_axis_id: string
}

export type ChartSpec = {
  chart_type: "line" | "bar" | "area" | "scatter" | "pie" | "composed"
  title: string
  subtitle: string | null
  caption: string | null
  x_axis: {
    data_key: string
    label: string | null
    format: ChartValueFormat
    currency_code: string | null
    tick_angle: number
  }
  y_axes: {
    id: string
    label: string | null
    format: "number" | "currency" | "percent"
    currency_code: string | null
    minimum: number | null
    maximum: number | null
    orientation: "left" | "right"
    scale: "auto" | "linear" | "log"
  }[]
  series: ChartSeries[]
  data: Record<string, string | number | boolean | null>[]
  options: {
    height: number
    show_grid: boolean
    show_legend: boolean
    show_tooltip: boolean
    horizontal: boolean
    donut: boolean
    pie_labels: boolean
    theme: {
      background_color: string | null
      text_color: string | null
      grid_color: string | null
      palette: string[]
    }
  }
}
