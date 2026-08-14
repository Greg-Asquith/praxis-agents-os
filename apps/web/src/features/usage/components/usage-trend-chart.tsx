// apps/web/src/features/usage/components/usage-trend-chart.tsx

import { useState } from "react"
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import type { DailyUsagePoint } from "@/features/usage/types"
import { formatTokenCount, formatUsd } from "@/features/usage/format"

type Metric = "cost" | "tokens"

export function UsageTrendChart({ daily }: { daily: DailyUsagePoint[] }) {
  const [metric, setMetric] = useState<Metric>("cost")
  const data = daily.map((point) => ({
    ...point,
    cost: Number(point.estimated_cost_usd),
    label: new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" }).format(
      new Date(`${point.date}T00:00:00Z`)
    ),
  }))
  const dataKey = metric === "cost" ? "cost" : "tokens"

  return (
    <section aria-labelledby="usage-trend-heading" className="border-border border-t pt-5">
      <div className="mb-4 flex items-center justify-between gap-4">
        <div>
          <h3 className="font-heading font-medium" id="usage-trend-heading">
            Daily usage
          </h3>
          <p className="text-muted-foreground mt-1 text-xs">Timezone: UTC</p>
        </div>
        <Tabs
          value={metric}
          onValueChange={(value) => {
            setMetric(value as Metric)
          }}
        >
          <TabsList variant="micro">
            <TabsTrigger value="cost">Cost</TabsTrigger>
            <TabsTrigger value="tokens">Tokens</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>
      <div className="h-64 w-full" data-testid="usage-trend-chart">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ bottom: 0, left: 0, right: 8, top: 8 }}>
            <defs>
              <linearGradient id="usage-chart-fill" x1="0" x2="0" y1="0" y2="1">
                <stop offset="5%" stopColor="var(--chart-1)" stopOpacity={0.28} />
                <stop offset="95%" stopColor="var(--chart-1)" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
            <XAxis
              axisLine={false}
              dataKey="label"
              minTickGap={24}
              tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
              tickLine={false}
            />
            <YAxis
              axisLine={false}
              tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
              tickFormatter={(value: number) =>
                metric === "cost" ? formatUsd(String(value)) : formatTokenCount(value)
              }
              tickLine={false}
              width={64}
            />
            <Tooltip
              contentStyle={{
                background: "var(--popover)",
                border: "1px solid var(--border)",
                borderRadius: "0.5rem",
                color: "var(--popover-foreground)",
                fontSize: "0.75rem",
              }}
              formatter={(value) =>
                metric === "cost" ? formatUsd(String(value)) : formatTokenCount(Number(value))
              }
            />
            <Area
              dataKey={dataKey}
              fill="url(#usage-chart-fill)"
              stroke="var(--chart-1)"
              strokeWidth={2}
              type="monotone"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </section>
  )
}
