// apps/web/src/features/usage/format.ts

import type { PricingCoverage, TokenCounts, UsageBreakdownRow } from "@/features/usage/types"

export const AI_USAGE_PURPOSES = [
  "agent_run",
  "conversation_naming",
  "history_summary",
  "kb_annotation",
  "web_search",
  "web_fetch",
  "image_generation",
  "embedding_kb_ingest",
  "embedding_kb_search",
  "embedding_memory_write",
  "embedding_memory_search",
  "embedding_memory_dedup",
] as const

export type AIUsagePurpose = (typeof AI_USAGE_PURPOSES)[number]

export const AI_TYPE_LABEL_BY_PURPOSE = {
  agent_run: "Agent conversations",
  conversation_naming: "Conversation housekeeping",
  history_summary: "Conversation housekeeping",
  kb_annotation: "Document processing",
  web_search: "Web research",
  web_fetch: "Web research",
  image_generation: "Image creation",
  embedding_kb_ingest: "Search & document indexing",
  embedding_kb_search: "Search & document indexing",
  embedding_memory_write: "Search & document indexing",
  embedding_memory_search: "Search & document indexing",
  embedding_memory_dedup: "Search & document indexing",
} satisfies Record<AIUsagePurpose, string>

const INTEGER_FORMATTER = new Intl.NumberFormat(undefined, { notation: "compact" })
const USD_FORMATTER = new Intl.NumberFormat("en-US", {
  currency: "USD",
  maximumFractionDigits: 4,
  minimumFractionDigits: 2,
  style: "currency",
})
const PERCENT_FORMATTER = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 1,
  style: "percent",
})

export function formatTokenCount(value: number) {
  return INTEGER_FORMATTER.format(value)
}

export function formatUsd(value: string | null) {
  return value === null ? "—" : USD_FORMATTER.format(Number(value))
}

export function formatShare(value: string | null) {
  return value === null ? "—" : PERCENT_FORMATTER.format(Number(value))
}

export function totalTokens(tokens: TokenCounts) {
  return tokens.input + tokens.cache_read + tokens.cache_write + tokens.output
}

export function groupPurposeBreakdownRows(rows: UsageBreakdownRow[]): UsageBreakdownRow[] {
  const groups = new Map<
    string,
    Omit<UsageBreakdownRow, "token_share" | "priced_cost_share"> & { pricedCost: number }
  >()

  for (const row of rows) {
    const label = isAIUsagePurpose(row.key)
      ? AI_TYPE_LABEL_BY_PURPOSE[row.key]
      : row.label || "Other AI usage"
    const current = groups.get(label) ?? emptyGroup(row.key, label)
    current.tokens_by_class.input += row.tokens_by_class.input
    current.tokens_by_class.cache_read += row.tokens_by_class.cache_read
    current.tokens_by_class.cache_write += row.tokens_by_class.cache_write
    current.tokens_by_class.output += row.tokens_by_class.output
    current.requests += row.requests
    current.pricing_coverage.priced_tokens += row.pricing_coverage.priced_tokens
    current.pricing_coverage.unpriced_tokens += row.pricing_coverage.unpriced_tokens
    current.pricing_coverage.priced_requests += row.pricing_coverage.priced_requests
    current.pricing_coverage.unpriced_requests += row.pricing_coverage.unpriced_requests
    current.pricing_coverage.priced_image_generations +=
      row.pricing_coverage.priced_image_generations
    current.pricing_coverage.unpriced_image_generations +=
      row.pricing_coverage.unpriced_image_generations
    if (row.estimated_cost_usd !== null) {
      current.estimated_cost_usd = "0"
      current.pricedCost += Number(row.estimated_cost_usd)
    }
    groups.set(label, current)
  }

  const grouped = [...groups.values()]
  const allTokens = grouped.reduce((sum, row) => sum + totalTokens(row.tokens_by_class), 0)
  const allPricedCost = grouped.reduce((sum, row) => sum + row.pricedCost, 0)
  return grouped.map(({ pricedCost, ...row }) => {
    const coveredTokens = row.pricing_coverage.priced_tokens + row.pricing_coverage.unpriced_tokens
    const coveredRequests =
      row.pricing_coverage.priced_requests + row.pricing_coverage.unpriced_requests
    return {
      ...row,
      estimated_cost_usd: row.estimated_cost_usd === null ? null : String(pricedCost),
      token_share: String(allTokens === 0 ? 0 : totalTokens(row.tokens_by_class) / allTokens),
      priced_cost_share:
        row.estimated_cost_usd === null || allPricedCost === 0
          ? null
          : String(pricedCost / allPricedCost),
      pricing_coverage: {
        ...row.pricing_coverage,
        token_coverage_percent: String(
          coveredTokens === 0 ? 0 : (row.pricing_coverage.priced_tokens / coveredTokens) * 100
        ),
        request_coverage_percent: String(
          coveredRequests === 0 ? 0 : (row.pricing_coverage.priced_requests / coveredRequests) * 100
        ),
      },
    }
  })
}

function isAIUsagePurpose(value: string): value is AIUsagePurpose {
  return value in AI_TYPE_LABEL_BY_PURPOSE
}

function emptyGroup(key: string, label: string) {
  const coverage: PricingCoverage = {
    priced_tokens: 0,
    unpriced_tokens: 0,
    token_coverage_percent: "0",
    priced_requests: 0,
    unpriced_requests: 0,
    request_coverage_percent: "0",
    priced_image_generations: 0,
    unpriced_image_generations: 0,
  }
  return {
    key,
    label,
    estimated_cost_usd: null,
    tokens_by_class: { input: 0, cache_read: 0, cache_write: 0, output: 0 },
    requests: 0,
    pricing_coverage: coverage,
    pricedCost: 0,
  }
}
