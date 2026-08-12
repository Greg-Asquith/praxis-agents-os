// apps/web/src/features/usage/components/usage-dashboard-panel.tsx

import { useMemo, useState } from "react"
import { ActivityIcon } from "lucide-react"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { EmptyState } from "@/components/ui/empty-state"
import { Skeleton } from "@/components/ui/skeleton"
import { Stat } from "@/components/ui/stat"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useUsageBreakdownQuery } from "@/features/usage/api/get-usage-breakdown"
import { useUsageSummaryQuery } from "@/features/usage/api/get-usage-summary"
import { CostQualityPanel } from "@/features/usage/components/cost-quality-panel"
import { UsageBreakdownTable } from "@/features/usage/components/usage-breakdown-table"
import { UsageEmptyState } from "@/features/usage/components/usage-empty-state"
import { UsageTokenStats } from "@/features/usage/components/usage-token-stats"
import { UsageTrendChart } from "@/features/usage/components/usage-trend-chart"
import { formatUsd, groupPurposeBreakdownRows } from "@/features/usage/format"
import type { UsageDimension, UsageRange } from "@/features/usage/types"
import { getErrorMessage } from "@/lib/api/errors"

type RangeDays = 7 | 30 | 90

const DIMENSIONS: { api: UsageDimension; label: string }[] = [
  { api: "agent", label: "Agents" },
  { api: "user", label: "People" },
  { api: "purpose", label: "AI Types" },
  { api: "model", label: "Models" },
]

export function UsageDashboardPanel() {
  const [days, setDays] = useState<RangeDays>(30)
  const [dimension, setDimension] = useState<UsageDimension>("agent")
  const [rangeAnchor] = useState(() => new Date())
  const range = useMemo(() => buildRange(rangeAnchor, days), [days, rangeAnchor])
  const summaryQuery = useUsageSummaryQuery(range)
  const breakdownQuery = useUsageBreakdownQuery({ ...range, dimension })

  if (summaryQuery.isPending || breakdownQuery.isPending) {
    return <UsageDashboardSkeleton />
  }

  if (summaryQuery.isError || breakdownQuery.isError) {
    return (
      <EmptyState
        description={getErrorMessage(summaryQuery.error ?? breakdownQuery.error)}
        icon={<ActivityIcon className="size-5" />}
        size="compact"
        title="Usage could not load"
      />
    )
  }

  const summary = summaryQuery.data
  const rawRows = breakdownQuery.data.rows
  const rows = dimension === "purpose" ? groupPurposeBreakdownRows(rawRows) : rawRows
  const hasUsage =
    summary.totals.requests > 0 ||
    Object.values(summary.totals.tokens_by_class).some((value) => value > 0)

  return (
    <Card className="border-0 bg-transparent shadow-none ring-0">
      <CardHeader className="px-1">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <CardTitle>AI Usage</CardTitle>
            <CardDescription className="mt-1">
              Understand how your team uses models and where estimated costs come from.
            </CardDescription>
          </div>
          <Tabs
            value={String(days)}
            onValueChange={(value) => {
              setDays(Number(value) as RangeDays)
            }}
          >
            <TabsList variant="micro">
              <TabsTrigger value="7">7 days</TabsTrigger>
              <TabsTrigger value="30">30 days</TabsTrigger>
              <TabsTrigger value="90">90 days</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-6 px-1">
        {!hasUsage ? (
          <UsageEmptyState />
        ) : (
          <>
            <Stat
              label={`Estimated cost · last ${String(days)} days`}
              size="lg"
              value={formatUsd(summary.totals.estimated_cost_usd)}
              footnote="Estimated at the providers’ public API rates for the priced usage shown below."
            />
            <UsageTrendChart daily={summary.daily} />
            <UsageTokenStats tokens={summary.totals.tokens_by_class} />
            <section aria-labelledby="usage-breakdown-heading">
              <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
                <div>
                  <h3 className="font-heading text-lg font-medium" id="usage-breakdown-heading">
                    What drives usage
                  </h3>
                  <p className="text-muted-foreground mt-1 text-sm">
                    Compare estimated cost, tokens, and provider requests.
                  </p>
                </div>
                <Tabs
                  value={dimension}
                  onValueChange={(value) => {
                    setDimension(value as UsageDimension)
                  }}
                >
                  <TabsList variant="micro">
                    {DIMENSIONS.map((item) => (
                      <TabsTrigger key={item.api} value={item.api}>
                        {item.label}
                      </TabsTrigger>
                    ))}
                  </TabsList>
                </Tabs>
              </div>
              <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_18rem]">
                <UsageBreakdownTable rows={rows} />
                <CostQualityPanel coverage={summary.pricing_coverage} />
              </div>
            </section>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function buildRange(anchor: Date, days: RangeDays): UsageRange {
  return {
    from: new Date(anchor.getTime() - days * 24 * 60 * 60 * 1000).toISOString(),
    to: anchor.toISOString(),
  }
}

function UsageDashboardSkeleton() {
  return (
    <div aria-label="Loading usage" className="flex flex-col gap-6" role="status">
      <Skeleton className="h-8 w-40" />
      <Skeleton className="h-28 w-full" />
      <Skeleton className="h-64 w-full" />
      <Skeleton className="h-48 w-full" />
    </div>
  )
}
