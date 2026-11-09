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

type ForecastSimpleMethod = "average" | "same_period_last_cycle"

export type ForecastReliability = "good" | "limited" | "low"

type ForecastScore = { typicalError: number | null; rangeCoverage: number | null }

type ForecastHoliday = { date: string; region: string; name: string }

export type ForecastToolResult = {
  title: string
  unit: string | null
  frequency: ForecastFrequency
  method: string
  backtest: {
    periods: number
    startingPoints: number
    testedPoints: number
    simpleMethod: ForecastSimpleMethod
    simpleError: number | null
    covariateErrorChange: number | null
  }
  holidays: ForecastHoliday[]
  covariatesUsed: boolean
  reliability: ForecastReliability
  caveats: string[]
  chart: {
    periods: string[]
    history: (number | null)[]
    forecast: ForecastBand
    baseline: ForecastBand | null
    backtest: { forecast: ForecastScore; baseline: ForecastScore | null }
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
const RELIABILITIES: ReadonlySet<ForecastReliability> = new Set(["good", "limited", "low"])
const SIMPLE_METHODS: ReadonlySet<ForecastSimpleMethod> = new Set([
  "average",
  "same_period_last_cycle",
])

// The public result of a completed forecast_series call, or null when it isn't one.
export function forecastToolResult(value: unknown): ForecastToolResult | null {
  if (
    !isRecord(value) ||
    typeof value["title"] !== "string" ||
    (value["unit"] !== null && typeof value["unit"] !== "string") ||
    !isOneOf(FREQUENCIES, value["frequency"]) ||
    typeof value["method"] !== "string" ||
    !isRecord(value["backtest"]) ||
    !Array.isArray(value["holidays"]) ||
    typeof value["covariates_used"] !== "boolean" ||
    !isOneOf(RELIABILITIES, value["reliability"]) ||
    !isStringArray(value["caveats"])
  ) {
    return null
  }
  const backtest = value["backtest"]
  const chart = forecastChart(value["chart"])
  if (
    !chart ||
    typeof backtest["periods"] !== "number" ||
    typeof backtest["starting_points"] !== "number" ||
    typeof backtest["tested_points"] !== "number" ||
    !isOneOf(SIMPLE_METHODS, backtest["simple_method"]) ||
    !isNullableFiniteNumber(backtest["simple_error"]) ||
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
      startingPoints: backtest["starting_points"],
      testedPoints: backtest["tested_points"],
      simpleMethod: backtest["simple_method"],
      simpleError: backtest["simple_error"],
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
    covariatesUsed: value["covariates_used"],
    reliability: value["reliability"],
    caveats: value["caveats"],
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
  const tested = score(value["backtest"]["forecast"])
  const testedBaseline =
    value["backtest"]["baseline"] === null ? null : score(value["backtest"]["baseline"])
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

function score(value: unknown): ForecastScore | null {
  return isRecord(value) &&
    isNullableFiniteNumber(value["typical_error"]) &&
    isNullableFiniteNumber(value["range_coverage"])
    ? { typicalError: value["typical_error"], rangeCoverage: value["range_coverage"] }
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

const SIMPLE_METHOD_NAMES: Record<ForecastSimpleMethod, string> = {
  average: "the average of past values",
  same_period_last_cycle: "repeating the last cycle",
}

export type ForecastBacktestSummary = ForecastScore & {
  periods: number
  periodName: string
  startingPoints: number
  simpleName: string
  simpleError: number | null
}

// The test results for whichever forecast is on show.
export function forecastBacktestSummary(
  result: ForecastToolResult,
  useCovariates: boolean
): ForecastBacktestSummary {
  const { backtest, chart } = result
  const score =
    useCovariates || !chart.backtest.baseline ? chart.backtest.forecast : chart.backtest.baseline
  return {
    ...score,
    periods: backtest.periods,
    periodName: FORECAST_PERIOD_NAMES[result.frequency],
    startingPoints: backtest.startingPoints,
    simpleName: SIMPLE_METHOD_NAMES[backtest.simpleMethod],
    simpleError: backtest.simpleError,
  }
}
