// apps/web/src/features/usage/types.ts

export type UsageDimension = "agent" | "user" | "purpose" | "model"
export type PlatformUsageDimension = "workspace" | "user" | "purpose" | "model"

export type TokenCounts = {
  input: number
  cache_read: number
  cache_write: number
  output: number
}

export type PricingCoverage = {
  priced_tokens: number
  unpriced_tokens: number
  token_coverage_percent: string
  priced_requests: number
  unpriced_requests: number
  request_coverage_percent: string
  priced_image_generations: number
  unpriced_image_generations: number
}

type UsageTotals = {
  estimated_cost_usd: string
  tokens_by_class: TokenCounts
  requests: number
}

export type DailyUsagePoint = {
  date: string
  estimated_cost_usd: string
  tokens: number
  requests: number
}

type ModelUsageRow = {
  provider: string
  model: string
  estimated_cost_usd: string | null
  tokens: number
  requests: number
  token_share: string
  priced_cost_share: string | null
  pricing_coverage: PricingCoverage
}

export type UsageSummary = {
  from: string
  to: string
  timezone: "UTC"
  totals: UsageTotals
  pricing_coverage: PricingCoverage
  daily: DailyUsagePoint[]
  models: ModelUsageRow[]
}

export type UsageBreakdownRow = {
  key: string
  label: string
  estimated_cost_usd: string | null
  tokens_by_class: TokenCounts
  requests: number
  token_share: string
  priced_cost_share: string | null
  pricing_coverage: PricingCoverage
}

export type UsageBreakdown = {
  from: string
  to: string
  timezone: "UTC"
  dimension: UsageDimension
  rows: UsageBreakdownRow[]
}

export type PlatformUsageBreakdown = Omit<UsageBreakdown, "dimension"> & {
  dimension: PlatformUsageDimension
}

export type UsageRange = {
  from: string
  to: string
}
