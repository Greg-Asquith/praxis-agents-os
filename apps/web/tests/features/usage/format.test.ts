import { readFileSync } from "node:fs"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { UsageEmptyState } from "@/features/usage/components/usage-empty-state"
import {
  AI_TYPE_LABEL_BY_PURPOSE,
  AI_USAGE_PURPOSES,
  formatShare,
  formatUsd,
  groupPurposeBreakdownRows,
} from "@/features/usage/format"
import type { UsageBreakdownRow } from "@/features/usage/types"

describe("usage presentation", () => {
  it("keeps AI type labels exhaustive against the backend purpose domain", () => {
    const backendDomain = readFileSync(
      new URL("../../../../api/services/ai_usage/domain.py", import.meta.url),
      "utf8"
    )
    const backendPurposes = [...backendDomain.matchAll(/^PURPOSE_[A-Z_]+ = "([^"]+)"$/gm)]
      .map((match) => match[1])
      .sort()

    expect([...AI_USAGE_PURPOSES].sort()).toEqual(backendPurposes)
    expect(Object.keys(AI_TYPE_LABEL_BY_PURPOSE).sort()).toEqual(backendPurposes)
  })

  it("formats unknown cost as an em dash and decimal shares as percentages", () => {
    expect(formatUsd(null)).toBe("—")
    expect(formatUsd("12.5")).toBe("$12.50")
    expect(formatShare("0.125")).toBe("12.5%")
  })

  it("groups raw purposes into plain-language AI types", () => {
    const rows = [usageRow("web_search", "1.25", 20), usageRow("web_fetch", "0.75", 30)]

    expect(groupPurposeBreakdownRows(rows)).toEqual([
      expect.objectContaining({
        estimated_cost_usd: "2",
        label: "Web research",
        requests: 2,
        token_share: "1",
      }),
    ])
  })

  it("does not crash when an older API returns an unknown purpose", () => {
    const grouped = groupPurposeBreakdownRows([usageRow("legacy_helper", "0.1", 5)])

    expect(grouped[0]).toEqual(
      expect.objectContaining({ key: "legacy_helper", label: "legacy_helper" })
    )
  })

  it("renders the metering-aware empty state", () => {
    const html = renderToStaticMarkup(createElement(UsageEmptyState))

    expect(html).toContain("No AI usage in this period")
    expect(html).toContain("Data collection began when usage metering landed")
  })
})

function usageRow(key: string, cost: string, input: number): UsageBreakdownRow {
  return {
    key,
    label: key,
    estimated_cost_usd: cost,
    tokens_by_class: { input, cache_read: 0, cache_write: 0, output: 0 },
    requests: 1,
    token_share: "0",
    priced_cost_share: "0",
    pricing_coverage: {
      priced_tokens: input,
      unpriced_tokens: 0,
      token_coverage_percent: "100",
      priced_requests: 1,
      unpriced_requests: 0,
      request_coverage_percent: "100",
      priced_image_generations: 0,
      unpriced_image_generations: 0,
    },
  }
}
