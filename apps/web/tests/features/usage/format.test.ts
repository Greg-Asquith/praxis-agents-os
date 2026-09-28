import { describe, expect, it } from "vitest"

import { formatShare, formatUsd, groupPurposeBreakdownRows } from "@/features/usage/format"
import type { UsageBreakdownRow } from "@/features/usage/types"

describe("usage presentation", () => {
  it("formats unknown cost as an em dash and decimal shares as percentages", () => {
    expect(formatUsd(null)).toBe("—")
    expect(formatUsd("12.5")).toBe("$12.50")
    expect(formatShare("0.125")).toBe("12.5%")
  })

  it("groups purposes, sums only priced cost, and leaves fully unpriced groups unknown", () => {
    const grouped = groupPurposeBreakdownRows([
      usageRow("web_search", "1.25", 20),
      usageRow("web_fetch", null, 30),
      usageRow("agent_run", "3.75", 50),
      usageRow("classification", null, 100),
    ])

    expect(grouped).toEqual([
      expect.objectContaining({
        key: "web_search",
        estimated_cost_usd: "1.25",
        priced_cost_share: "0.25",
        token_share: "0.25",
        requests: 2,
      }),
      expect.objectContaining({
        key: "agent_run",
        estimated_cost_usd: "3.75",
        priced_cost_share: "0.75",
      }),
      expect.objectContaining({
        key: "classification",
        estimated_cost_usd: null,
        priced_cost_share: null,
        token_share: "0.5",
      }),
    ])
    expect(grouped[0]?.pricing_coverage).toMatchObject({
      priced_tokens: 20,
      unpriced_tokens: 30,
      token_coverage_percent: "40",
      request_coverage_percent: "50",
    })
  })
})

function usageRow(key: string, cost: string | null, input: number): UsageBreakdownRow {
  const priced = cost !== null
  return {
    key,
    label: key,
    estimated_cost_usd: cost,
    tokens_by_class: { input, cache_read: 0, cache_write: 0, output: 0 },
    requests: 1,
    token_share: "0",
    priced_cost_share: null,
    pricing_coverage: {
      priced_tokens: priced ? input : 0,
      unpriced_tokens: priced ? 0 : input,
      token_coverage_percent: priced ? "100" : "0",
      priced_requests: priced ? 1 : 0,
      unpriced_requests: priced ? 0 : 1,
      request_coverage_percent: priced ? "100" : "0",
      priced_image_generations: 0,
      unpriced_image_generations: 0,
    },
  }
}
