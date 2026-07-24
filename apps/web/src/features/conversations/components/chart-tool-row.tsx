// apps/web/src/features/conversations/components/chart-tool-row.tsx

import { lazy, Suspense, useEffect, useMemo, useRef } from "react"
import { BarChart3Icon } from "lucide-react"

import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { Badge } from "@/components/ui/badge"
import { chartSpec } from "@/features/conversations/native-tools/chart-tool"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { pluralize } from "@/lib/format"

const DataChart = lazy(() =>
  import("@/components/tool-ui/chart").then((module) => ({ default: module.DataChart }))
)

export function ChartToolRow({ activity }: { activity: ToolActivity }) {
  const spec = useMemo(
    () => (activity.status === "completed" ? chartSpec(activity.args) : null),
    [activity.args, activity.status]
  )
  const warnedInvalidSpec = useRef(false)

  useEffect(() => {
    if (
      import.meta.env.DEV &&
      activity.status === "completed" &&
      !spec &&
      !warnedInvalidSpec.current
    ) {
      warnedInvalidSpec.current = true
      console.warn(
        "Build Chart result could not be rendered because its spec was invalid.",
        activity.args
      )
    }
  }, [activity.args, activity.status, spec])

  if (activity.status === "running") {
    return (
      <FanOutSkeleton
        heading={<ChartHeading />}
        label="Building chart…"
        summary="Preparing the chart"
      />
    )
  }
  if (activity.status !== "completed") {
    return null
  }

  if (!spec) {
    return null
  }
  const pointCount = spec.data.length
  const seriesCount = spec.series.length
  return (
    <ToolResultCard
      ariaLabel={`Chart: ${spec.title}`}
      defaultOpen
      details={[
        { label: "Chart", value: spec.title },
        { label: "Type", value: chartTypeLabel(spec.chart_type) },
        {
          label: "Data",
          value: `${String(pointCount)} ${pluralize(pointCount, "Point")} · ${String(seriesCount)} ${pluralize(seriesCount, "Series", "Series")}`,
        },
      ]}
      heading={<ChartHeading />}
      trailing={<Badge variant="success">Ready</Badge>}
    >
      <Suspense
        fallback={
          <div
            aria-label={`Loading chart: ${spec.title}`}
            className="bg-muted/30 flex min-h-52 items-center justify-center rounded-lg"
            role="status"
          >
            <span className="text-muted-foreground text-sm">Loading chart…</span>
          </div>
        }
      >
        <DataChart spec={spec} />
      </Suspense>
    </ToolResultCard>
  )
}

function ChartHeading() {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <BarChart3Icon className="text-muted-foreground size-4 shrink-0" />
      <span>Build Chart</span>
    </span>
  )
}

function chartTypeLabel(value: string): string {
  return value === "composed" ? "Combined" : `${value.charAt(0).toUpperCase()}${value.slice(1)}`
}
