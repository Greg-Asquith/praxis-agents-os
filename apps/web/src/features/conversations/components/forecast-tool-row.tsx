// apps/web/src/features/conversations/components/forecast-tool-row.tsx

import { lazy, Suspense, useMemo, useState } from "react"
import { TrendingUpIcon } from "lucide-react"

import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { ToolHeading } from "@/components/tool-ui/tool-heading"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  FORECAST_PERIOD_NAMES,
  forecastBacktestSummary,
  forecastToolResult,
  type ForecastReliability,
  type ForecastToolResult,
} from "@/features/conversations/native-tools/forecast-tool"
import { pluralize } from "@/lib/format"

const ForecastChart = lazy(() =>
  import("@/features/conversations/components/forecast-chart").then((module) => ({
    default: module.ForecastChart,
  }))
)

const PERCENT = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0, style: "percent" })

const RELIABILITY_BADGES = {
  good: { label: "Good Reliability", variant: "success" },
  limited: { label: "Limited Reliability", variant: "warning" },
  low: { label: "Low Reliability", variant: "destructive" },
} as const

const CAVEATS_TITLE: Record<ForecastReliability, string> = {
  good: "Good To Know",
  limited: "Use With Care",
  low: "Don't Rely On This Forecast Alone",
}

export function ForecastToolRow({ activity }: { activity: ToolActivity }) {
  const result = useMemo(
    () => (activity.status === "completed" ? forecastToolResult(activity.result) : null),
    [activity.result, activity.status]
  )
  const [covariateChoice, setCovariateChoice] = useState<boolean | null>(null)
  const heading = <ToolHeading icon={TrendingUpIcon}>Forecast</ToolHeading>

  if (!result) {
    return (
      <FanOutSkeleton heading={heading} label="Forecasting…" summary="Preparing the forecast" />
    )
  }
  const { chart } = result
  const useCovariates = covariateChoice ?? result.covariatesUsed
  const horizon = chart.forecast.median.length
  return (
    <ToolResultCard
      ariaLabel={`Forecast: ${result.title}`}
      defaultOpen
      details={[
        { label: "Forecast", value: result.title },
        {
          label: "Horizon",
          value: `${String(horizon)} ${pluralize(horizon, FORECAST_PERIOD_NAMES[result.frequency])}`,
        },
        { label: "Method", value: result.method },
      ]}
      heading={heading}
      trailing={
        <>
          <ReliabilityBadge reliability={result.reliability} />
          {useCovariates ? <CovariateEffect change={result.backtest.covariateErrorChange} /> : null}
        </>
      }
    >
      <div className="grid min-w-0 gap-2">
        <Suspense
          fallback={
            <div
              aria-label={`Loading forecast: ${result.title}`}
              className="bg-muted/30 flex min-h-64 items-center justify-center rounded-lg"
              role="status"
            >
              <span className="text-muted-foreground text-sm">Loading forecast…</span>
            </div>
          }
        >
          <ForecastChart
            onUseCovariatesChange={setCovariateChoice}
            result={result}
            useCovariates={useCovariates}
          />
        </Suspense>
        {result.caveats.length > 0 ? (
          <Alert variant={result.reliability === "low" ? "destructive" : "default"}>
            <AlertTitle>{CAVEATS_TITLE[result.reliability]}</AlertTitle>
            <AlertDescription>
              <ul className="grid list-disc gap-1 pl-4">
                {result.caveats.map((caveat) => (
                  <li key={caveat}>{caveat}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        ) : null}
        <p className="text-muted-foreground text-xs">{footer(result, useCovariates)}</p>
      </div>
    </ToolResultCard>
  )
}

function ReliabilityBadge({ reliability }: { reliability: ForecastReliability }) {
  const { label, variant } = RELIABILITY_BADGES[reliability]
  return <Badge variant={variant}>{label}</Badge>
}

function CovariateEffect({ change }: { change: number | null }) {
  if (change === null) {
    return null
  }
  const percent = PERCENT.format(Math.abs(change))
  if (Math.round(Math.abs(change) * 100) === 0) {
    return <Badge variant="secondary">Same Error With Covariates</Badge>
  }
  return change < 0 ? (
    <Badge variant="success">{percent} Lower Error With Covariates</Badge>
  ) : (
    <Badge variant="warning">{percent} Higher Error With Covariates</Badge>
  )
}

function footer(result: ForecastToolResult, useCovariates: boolean): string {
  const summary = forecastBacktestSummary(result, useCovariates)
  const ahead = `${String(summary.periods)} ${pluralize(summary.periods, summary.periodName)} ahead`
  const tested = `${result.method}, tested ${ahead} from ${String(summary.startingPoints)} ${pluralize(summary.startingPoints, "point")} in the history`
  return [
    summary.typicalError === null
      ? null
      : `Typically within ${PERCENT.format(summary.typicalError)}`,
    summary.simpleError === null
      ? null
      : `Compared with ${PERCENT.format(summary.simpleError)} for ${summary.simpleName}`,
    summary.rangeCoverage === null
      ? null
      : `${PERCENT.format(summary.rangeCoverage)} of actual values fell in the likely range`,
    tested,
  ]
    .filter((part) => part !== null)
    .join(" · ")
}
