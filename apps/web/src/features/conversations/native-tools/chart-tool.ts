// apps/web/src/features/conversations/native-tools/chart-tool.ts

import type { ChartSeries, ChartSpec } from "@/components/tool-ui/chart-types"
import { isRecord } from "@/lib/guards"

export const BUILD_CHART_TOOL_NAME = "build_chart"

const CHART_TYPES = new Set(["line", "bar", "area", "scatter", "pie", "composed"])
const SERIES_TYPES = new Set(["line", "bar", "area"])
const X_FORMATS = new Set(["text", "number", "currency", "percent", "date", "datetime"])
const NUMERIC_FORMATS = new Set(["number", "currency", "percent"])
const CURVES = new Set(["linear", "monotone", "step"])
const LINE_STYLES = new Set(["solid", "dashed", "dotted"])
const SCALES = new Set(["auto", "linear", "log"])
const HEX_COLOR = /^#[0-9a-f]{6}$/i
const CURRENCY_CODE = /^[A-Z]{3}$/
const DECIMAL_NUMBER = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/
const DEFAULT_AXIS_ID = "primary"

const ROOT_KEYS = new Set([
  "caption",
  "chart_type",
  "data",
  "options",
  "series",
  "subtitle",
  "title",
  "x_axis",
  "y_axes",
])
const X_AXIS_KEYS = new Set(["currency_code", "data_key", "format", "label", "tick_angle"])
const Y_AXIS_KEYS = new Set([
  "currency_code",
  "format",
  "id",
  "label",
  "maximum",
  "minimum",
  "orientation",
  "scale",
])
const SERIES_KEYS = new Set([
  "color",
  "connect_nulls",
  "currency_code",
  "curve",
  "data_key",
  "format",
  "kind",
  "label",
  "line_style",
  "show_points",
  "stack_id",
  "y_axis_id",
])
const OPTION_KEYS = new Set([
  "donut",
  "height",
  "horizontal",
  "pie_labels",
  "show_grid",
  "show_legend",
  "show_tooltip",
  "theme",
])
const THEME_KEYS = new Set(["background_color", "grid_color", "palette", "text_color"])

export function chartSpec(value: unknown): ChartSpec | null {
  const candidate =
    isRecord(value) && Object.keys(value).length === 1 && isRecord(value["spec"])
      ? value["spec"]
      : value
  if (
    !isRecord(candidate) ||
    !onlyKeys(candidate, ROOT_KEYS) ||
    !enumValue(candidate["chart_type"], CHART_TYPES) ||
    !boundedString(candidate["title"], 1, 120) ||
    !optionalString(candidate["subtitle"], 240) ||
    !optionalString(candidate["caption"], 500)
  ) {
    return null
  }

  const chartType = candidate["chart_type"] as ChartSpec["chart_type"]
  const xAxis = parseXAxis(candidate["x_axis"])
  const yAxes = parseYAxes(candidate["y_axes"])
  if (!xAxis || !yAxes) {
    return null
  }
  const defaultAxisId = yAxes[0]?.id ?? DEFAULT_AXIS_ID
  if (
    !Array.isArray(candidate["series"]) ||
    candidate["series"].length < 1 ||
    candidate["series"].length > 5
  ) {
    return null
  }
  const series = candidate["series"].map((item) => parseSeries(item, chartType, defaultAxisId))
  if (series.some((item) => item === null)) {
    return null
  }
  const normalizedSeries = series as ChartSeries[]
  const axisIds = new Set(yAxes.map((axis) => axis.id))
  if (normalizedSeries.some((item) => !axisIds.has(item.y_axis_id))) {
    return null
  }
  const data = parseData(candidate["data"], normalizedSeries, chartType, xAxis.data_key)
  const options = parseOptions(candidate["options"], chartType)
  if (!data || !options) {
    return null
  }

  return {
    caption: stringOrNull(candidate["caption"]),
    chart_type: chartType,
    data,
    options,
    series: normalizedSeries,
    subtitle: stringOrNull(candidate["subtitle"]),
    title: candidate["title"],
    x_axis: xAxis,
    y_axes: yAxes,
  }
}

function parseXAxis(value: unknown): ChartSpec["x_axis"] | null {
  if (
    !isRecord(value) ||
    !onlyKeys(value, X_AXIS_KEYS) ||
    !dataKey(value["data_key"]) ||
    !optionalString(value["label"], 80) ||
    !optionalEnum(value["format"], X_FORMATS) ||
    !optionalCurrency(value["currency_code"]) ||
    !optionalInteger(value["tick_angle"], -90, 90)
  ) {
    return null
  }
  return {
    currency_code: stringOrNull(value["currency_code"]),
    data_key: value["data_key"],
    format: enumDefault(value["format"], X_FORMATS, "text"),
    label: stringOrNull(value["label"]),
    tick_angle: typeof value["tick_angle"] === "number" ? value["tick_angle"] : 0,
  }
}

function parseYAxes(value: unknown): ChartSpec["y_axes"] | null {
  const entries = value === undefined ? [{}] : value
  if (!Array.isArray(entries) || entries.length < 1 || entries.length > 4) {
    return null
  }
  const axes = entries.map((entry, index) => parseYAxis(entry, index))
  return axes.some((axis) => axis === null) ? null : (axes as ChartSpec["y_axes"])
}

function parseYAxis(value: unknown, index: number): ChartSpec["y_axes"][number] | null {
  if (
    !isRecord(value) ||
    !onlyKeys(value, Y_AXIS_KEYS) ||
    !optionalString(value["id"], 40, 1) ||
    !optionalString(value["label"], 80) ||
    !optionalEnum(value["format"], NUMERIC_FORMATS) ||
    !optionalCurrency(value["currency_code"]) ||
    !optionalNumber(value["minimum"]) ||
    !optionalNumber(value["maximum"]) ||
    (value["orientation"] !== undefined &&
      value["orientation"] !== "left" &&
      value["orientation"] !== "right") ||
    !optionalEnum(value["scale"], SCALES)
  ) {
    return null
  }
  const id = typeof value["id"] === "string" ? value["id"] : index === 0 ? DEFAULT_AXIS_ID : null
  const minimum = numberOrNull(value["minimum"])
  const maximum = numberOrNull(value["maximum"])
  const scale = enumDefault<ChartSpec["y_axes"][number]["scale"]>(value["scale"], SCALES, "auto")
  if (
    id === null ||
    (minimum !== null && maximum !== null && minimum >= maximum) ||
    (scale === "log" && minimum !== null && minimum <= 0)
  ) {
    return null
  }
  return {
    currency_code: stringOrNull(value["currency_code"]),
    format: enumDefault(value["format"], NUMERIC_FORMATS, "number"),
    id,
    label: stringOrNull(value["label"]),
    maximum,
    minimum,
    orientation: value["orientation"] === "right" ? "right" : "left",
    scale,
  }
}

function parseSeries(
  value: unknown,
  chartType: ChartSpec["chart_type"],
  defaultAxisId: string
): ChartSeries | null {
  if (
    !isRecord(value) ||
    !onlyKeys(value, SERIES_KEYS) ||
    !dataKey(value["data_key"]) ||
    !boundedString(value["label"], 1, 80) ||
    !optionalEnum(value["kind"], SERIES_TYPES, true) ||
    !optionalEnum(value["format"], NUMERIC_FORMATS) ||
    !optionalCurrency(value["currency_code"]) ||
    !optionalString(value["y_axis_id"], 40, 1) ||
    !optionalHex(value["color"]) ||
    !optionalString(value["stack_id"], 40, 1) ||
    !optionalEnum(value["curve"], CURVES) ||
    !optionalBoolean(value["connect_nulls"]) ||
    !optionalBoolean(value["show_points"]) ||
    !optionalEnum(value["line_style"], LINE_STYLES)
  ) {
    return null
  }
  return {
    color: stringOrNull(value["color"]),
    connect_nulls: value["connect_nulls"] === true,
    currency_code: stringOrNull(value["currency_code"]),
    curve: enumDefault(value["curve"], CURVES, "monotone"),
    data_key: value["data_key"],
    format: enumDefault(value["format"], NUMERIC_FORMATS, "number"),
    kind: chartType === "composed" ? enumDefault(value["kind"], SERIES_TYPES, "line") : null,
    label: value["label"],
    line_style: enumDefault(value["line_style"], LINE_STYLES, "solid"),
    show_points: value["show_points"] === true,
    stack_id: stringOrNull(value["stack_id"]),
    y_axis_id: typeof value["y_axis_id"] === "string" ? value["y_axis_id"] : defaultAxisId,
  }
}

function parseData(
  value: unknown,
  series: ChartSeries[],
  chartType: ChartSpec["chart_type"],
  xDataKey: string
): ChartSpec["data"] | null {
  if (!Array.isArray(value) || value.length < 1 || value.length > 200) {
    return null
  }
  const numericKeys = new Set(series.map((item) => item.data_key))
  if (chartType === "scatter") {
    numericKeys.add(xDataKey)
  }
  const rows: ChartSpec["data"] = []
  for (const candidate of value) {
    if (!isRecord(candidate) || Object.keys(candidate).length > 20 || !(xDataKey in candidate)) {
      return null
    }
    const row: ChartSpec["data"][number] = {}
    for (const [key, item] of Object.entries(candidate)) {
      if (
        !dataKey(key) ||
        (typeof item === "string" && item.length > 500) ||
        (item !== null &&
          typeof item !== "string" &&
          typeof item !== "number" &&
          typeof item !== "boolean")
      ) {
        return null
      }
      row[key] = item
    }
    for (const key of numericKeys) {
      const number = coerceNumber(row[key])
      if (number === undefined) {
        return null
      }
      row[key] = number
    }
    rows.push(row)
  }
  return rows
}

function parseOptions(
  value: unknown,
  chartType: ChartSpec["chart_type"]
): ChartSpec["options"] | null {
  const options = value === undefined ? {} : value
  if (
    !isRecord(options) ||
    !onlyKeys(options, OPTION_KEYS) ||
    !optionalInteger(options["height"], 240, 640) ||
    !optionalBoolean(options["show_grid"]) ||
    !optionalBoolean(options["show_legend"]) ||
    !optionalBoolean(options["show_tooltip"]) ||
    !optionalBoolean(options["horizontal"]) ||
    !optionalBoolean(options["donut"]) ||
    !optionalBoolean(options["pie_labels"])
  ) {
    return null
  }
  const theme = parseTheme(options["theme"])
  if (!theme) {
    return null
  }
  return {
    donut: chartType === "pie" && options["donut"] === true,
    height: typeof options["height"] === "number" ? options["height"] : 320,
    horizontal: chartType === "bar" && options["horizontal"] === true,
    pie_labels: options["pie_labels"] === true,
    show_grid: options["show_grid"] !== false,
    show_legend: options["show_legend"] !== false,
    show_tooltip: options["show_tooltip"] !== false,
    theme,
  }
}

function parseTheme(value: unknown): ChartSpec["options"]["theme"] | null {
  const theme = value === undefined ? {} : value
  if (
    !isRecord(theme) ||
    !onlyKeys(theme, THEME_KEYS) ||
    !optionalHex(theme["background_color"]) ||
    !optionalHex(theme["text_color"]) ||
    !optionalHex(theme["grid_color"]) ||
    (theme["palette"] !== undefined &&
      (!Array.isArray(theme["palette"]) ||
        theme["palette"].length > 12 ||
        theme["palette"].some((color) => typeof color !== "string" || !HEX_COLOR.test(color))))
  ) {
    return null
  }
  return {
    background_color: stringOrNull(theme["background_color"]),
    grid_color: stringOrNull(theme["grid_color"]),
    palette: (theme["palette"] as string[] | undefined) ?? [],
    text_color: stringOrNull(theme["text_color"]),
  }
}

function coerceNumber(value: unknown): number | null | undefined {
  if (value === null || value === undefined) {
    return null
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : undefined
  }
  if (typeof value !== "string") {
    return undefined
  }
  const normalized = value.trim()
  if (!DECIMAL_NUMBER.test(normalized)) {
    return undefined
  }
  const parsed = Number(normalized)
  return Number.isFinite(parsed) ? parsed : undefined
}

function onlyKeys(value: Record<string, unknown>, allowed: Set<string>) {
  return Object.keys(value).every((key) => allowed.has(key))
}

function dataKey(value: unknown): value is string {
  return (
    boundedString(value, 1, 100) &&
    value.trim() === value &&
    value !== "__proto__" &&
    value !== "constructor" &&
    value !== "prototype" &&
    !Array.from(value).some((character) => character.charCodeAt(0) < 32)
  )
}

function boundedString(value: unknown, minimum: number, maximum: number): value is string {
  return typeof value === "string" && value.length >= minimum && value.length <= maximum
}

function optionalString(value: unknown, maximum: number, minimum = 0) {
  return value === undefined || value === null || boundedString(value, minimum, maximum)
}

function optionalNumber(value: unknown) {
  return (
    value === undefined || value === null || (typeof value === "number" && Number.isFinite(value))
  )
}

function optionalInteger(value: unknown, minimum: number, maximum: number) {
  return (
    value === undefined ||
    (typeof value === "number" && Number.isInteger(value) && value >= minimum && value <= maximum)
  )
}

function optionalBoolean(value: unknown) {
  return value === undefined || typeof value === "boolean"
}

function optionalCurrency(value: unknown) {
  return (
    value === undefined ||
    value === null ||
    (typeof value === "string" && CURRENCY_CODE.test(value))
  )
}

function optionalHex(value: unknown) {
  return (
    value === undefined || value === null || (typeof value === "string" && HEX_COLOR.test(value))
  )
}

function enumValue(value: unknown, values: Set<string>): value is string {
  return typeof value === "string" && values.has(value)
}

function optionalEnum(value: unknown, values: Set<string>, allowNull = false) {
  return value === undefined || (allowNull && value === null) || enumValue(value, values)
}

function enumDefault<T extends string>(value: unknown, values: Set<string>, fallback: T): T {
  return enumValue(value, values) ? (value as T) : fallback
}

function stringOrNull(value: unknown): string | null {
  return typeof value === "string" ? value : null
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}
