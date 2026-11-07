// apps/web/src/features/conversations/native-tools/forecast-tool.ts

import { isNullableFiniteNumber, isOneOf, isRecord, isStringArray } from "@/lib/guards"

export const FORECAST_SERIES_TOOL_NAME = "forecast_series"

type ForecastFrequency = "hourly" | "daily" | "weekly" | "monthly"

type ForecastBand = { median: number[]; low: number[]; high: number[] }

export type ForecastCovariate = {
  name: string
  source: "holiday" | "provided"
  kind: "number" | "category"
  // Covers the history window, plus the horizon for known-future covariates.
  values: (number | null)[]
  labels: string[] | null
}

type ForecastHoliday = { date: string; region: string; name: string }

export type ForecastToolResult = {
  title: string
  unit: string | null
  frequency: ForecastFrequency
  method: string
  backtest: {
    periods: number
    typicalError: number | null
    rangeCoverage: number | null
    covariateErrorChange: number | null
  }
  holidays: ForecastHoliday[]
  chart: {
    periods: string[]
    history: (number | null)[]
    forecast: ForecastBand
    baseline: ForecastBand | null
    backtest: { forecast: ForecastBand; baseline: ForecastBand | null }
    covariates: ForecastCovariate[]
  }
}

const FREQUENCIES: ReadonlySet<ForecastFrequency> = new Set([
  "hourly",
  "daily",
  "weekly",
  "monthly",
])
const SOURCES: ReadonlySet<ForecastCovariate["source"]> = new Set(["holiday", "provided"])
const KINDS: ReadonlySet<ForecastCovariate["kind"]> = new Set(["number", "category"])

// The public result of a completed forecast_series call, or null when it isn't one.
export function forecastToolResult(value: unknown): ForecastToolResult | null {
  if (
    !isRecord(value) ||
    typeof value["title"] !== "string" ||
    (value["unit"] !== null && typeof value["unit"] !== "string") ||
    !isOneOf(FREQUENCIES, value["frequency"]) ||
    typeof value["method"] !== "string" ||
    !isRecord(value["backtest"]) ||
    !Array.isArray(value["holidays"])
  ) {
    return null
  }
  const backtest = value["backtest"]
  const chart = forecastChart(value["chart"])
  if (
    !chart ||
    typeof backtest["periods"] !== "number" ||
    !isNullableFiniteNumber(backtest["typical_error"]) ||
    !isNullableFiniteNumber(backtest["range_coverage"]) ||
    !isNullableFiniteNumber(backtest["covariate_error_change"])
  ) {
    return null
  }
  return {
    title: value["title"],
    unit: value["unit"],
    frequency: value["frequency"],
    method: value["method"],
    backtest: {
      periods: backtest["periods"],
      typicalError: backtest["typical_error"],
      rangeCoverage: backtest["range_coverage"],
      covariateErrorChange: backtest["covariate_error_change"],
    },
    holidays: value["holidays"].flatMap((item: unknown) =>
      isRecord(item) &&
      typeof item["date"] === "string" &&
      typeof item["region"] === "string" &&
      typeof item["name"] === "string"
        ? [{ date: item["date"], region: item["region"], name: item["name"] }]
        : []
    ),
    chart,
  }
}

function forecastChart(value: unknown): ForecastToolResult["chart"] | null {
  if (!isRecord(value) || !isStringArray(value["periods"]) || !isRecord(value["backtest"])) {
    return null
  }
  const periods = value["periods"]
  const history = nullableNumbers(value["history"])
  const forecast = band(value["forecast"])
  const baseline = value["baseline"] === null ? null : band(value["baseline"])
  const tested = band(value["backtest"]["forecast"])
  const testedBaseline =
    value["backtest"]["baseline"] === null ? null : band(value["backtest"]["baseline"])
  const covariates = Array.isArray(value["covariates"])
    ? value["covariates"].map(covariate)
    : [null]
  if (
    !history ||
    !forecast ||
    (value["baseline"] !== null && !baseline) ||
    !tested ||
    (value["backtest"]["baseline"] !== null && !testedBaseline) ||
    periods.length !== history.length + forecast.median.length ||
    (baseline !== null && baseline.median.length !== forecast.median.length) ||
    tested.median.length > history.length ||
    (testedBaseline !== null && testedBaseline.median.length !== tested.median.length) ||
    !covariates.every(
      (item) =>
        item !== null &&
        (item.values.length === history.length || item.values.length === periods.length)
    )
  ) {
    return null
  }
  return {
    periods,
    history,
    forecast,
    baseline,
    backtest: { forecast: tested, baseline: testedBaseline },
    covariates: covariates.filter((item) => item !== null),
  }
}

function covariate(value: unknown): ForecastCovariate | null {
  if (
    !isRecord(value) ||
    typeof value["name"] !== "string" ||
    !isOneOf(SOURCES, value["source"]) ||
    !isOneOf(KINDS, value["kind"]) ||
    (value["labels"] != null && !isStringArray(value["labels"]))
  ) {
    return null
  }
  const values = nullableNumbers(value["values"])
  return values
    ? {
        name: value["name"],
        source: value["source"],
        kind: value["kind"],
        values,
        labels: isStringArray(value["labels"]) ? value["labels"] : null,
      }
    : null
}

function band(value: unknown): ForecastBand | null {
  if (!isRecord(value)) {
    return null
  }
  const median = numbers(value["median"])
  const low = numbers(value["low"])
  const high = numbers(value["high"])
  return median && low && high && low.length === median.length && high.length === median.length
    ? { median, low, high }
    : null
}

function numbers(value: unknown): number[] | null {
  return Array.isArray(value) &&
    value.every((item): item is number => typeof item === "number" && Number.isFinite(item))
    ? value
    : null
}

function nullableNumbers(value: unknown): (number | null)[] | null {
  return Array.isArray(value) && value.every(isNullableFiniteNumber) ? value : null
}

export const FORECAST_PERIOD_NAMES: Record<ForecastFrequency, string> = {
  hourly: "hour",
  daily: "day",
  weekly: "week",
  monthly: "month",
}

export type ForecastBacktestSummary = {
  periods: number
  periodName: string
  typicalError: number | null
  rangeCoverage: number | null
}

// The backtest of the forecast on show; without covariates it's scored here from the chart series.
export function forecastBacktestSummary(
  result: ForecastToolResult,
  useCovariates: boolean
): ForecastBacktestSummary {
  const { backtest, chart } = result
  const periodName = FORECAST_PERIOD_NAMES[result.frequency]
  const baseline = chart.backtest.baseline
  if (useCovariates || !baseline) {
    return {
      periods: backtest.periods,
      periodName,
      typicalError: backtest.typicalError,
      rangeCoverage: backtest.rangeCoverage,
    }
  }
  const actuals = chart.history.slice(chart.history.length - baseline.median.length)
  let error = 0
  let total = 0
  let inside = 0
  let counted = 0
  actuals.forEach((actual, index) => {
    const median = baseline.median[index]
    const low = baseline.low[index]
    const high = baseline.high[index]
    if (actual === null || median === undefined || low === undefined || high === undefined) {
      return
    }
    error += Math.abs(median - actual)
    total += Math.abs(actual)
    inside += low <= actual && actual <= high ? 1 : 0
    counted += 1
  })
  return {
    periods: backtest.periods,
    periodName,
    typicalError: total > 0 ? error / total : null,
    rangeCoverage: counted > 0 ? inside / counted : null,
  }
}
