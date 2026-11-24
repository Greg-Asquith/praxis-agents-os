// apps/web/tests/features/conversations/components/tools/web/page-speed-result.test.ts

import { describe, expect, it } from "vitest"

import { pageSpeedReport } from "@/features/conversations/components/tools/web/page-speed-report"
import {
  metricRating,
  pageSpeedResult,
  scoreRating,
} from "@/features/conversations/components/tools/web/page-speed-result"

function row(url: string, fields: Record<string, unknown> = {}) {
  return {
    requested_url: url,
    final_url: null,
    scores: { performance: 92 },
    lab: { lcp_ms: 1800, cls: 0.02, tbt_ms: 40, fcp_ms: 900, speed_index_ms: 1500 },
    field: null,
    top_issues: [],
    report: null,
    error_class: null,
    ...fields,
  }
}

describe("pageSpeedResult", () => {
  it("bands pages by their lead score and keeps a row whose final URL isn't http(s)", () => {
    const redirected = {
      node: "praxis_untrusted",
      source_kind: "web_fetch",
      source_ref: "https://a.example/old",
      content: "javascript:alert(1)",
    }
    const result = pageSpeedResult({
      strategy: "mobile",
      categories: ["performance"],
      tested_at: "2026-11-23T10:00:00+00:00",
      tested: 3,
      not_checked: 1,
      budget_remaining: 10,
      report_file: null,
      origins: {},
      rows: [
        row("https://a.example/"),
        row("https://a.example/old", { scores: { performance: 50 }, final_url: redirected }),
        row("https://a.example/slow", { scores: { performance: 49 } }),
        row("https://a.example/late", { scores: {}, lab: null, error_class: "not_checked" }),
        row("https://a.example/seo", { scores: { seo: 40 } }),
      ],
    })

    expect(result?.rows.map((entry) => entry.outcome)).toEqual([
      "good",
      "needs_improvement",
      "poor",
      "not_tested",
      "poor",
    ])
    expect(result?.rows[4]?.lead).toEqual({ category: "seo", score: 40 })
    expect(result?.rows[1]?.finalUrl).toBeNull()
  })
})

describe("scoreRating", () => {
  it("starts the good band at 90", () => {
    expect(scoreRating(89)).toBe("needs_improvement")
    expect(scoreRating(90)).toBe("good")
  })
})

describe("metricRating", () => {
  it("rates a lab value against the bands for the device tested", () => {
    expect(metricRating("tbt_ms", 200, "mobile")).toBe("good")
    expect(metricRating("tbt_ms", 201, "mobile")).toBe("needs_improvement")
    expect(metricRating("tbt_ms", 600, "mobile")).toBe("needs_improvement")
    expect(metricRating("tbt_ms", 601, "mobile")).toBe("poor")
    expect(metricRating("tbt_ms", 150, "desktop")).toBe("good")
    expect(metricRating("tbt_ms", 151, "desktop")).toBe("needs_improvement")
    expect(metricRating("tbt_ms", 350, "desktop")).toBe("needs_improvement")
    expect(metricRating("tbt_ms", 400, "desktop")).toBe("poor")
  })

  it("keeps the shared band for a metric Lighthouse scores the same on both devices", () => {
    expect(metricRating("cls", 0.2, "desktop")).toBe("needs_improvement")
  })
})

describe("pageSpeedReport", () => {
  it("reads one page at its range and keeps a description's link text only", () => {
    const first = JSON.stringify({ requested_url: "https://a.example/", failed_audits: [] })
    const second = JSON.stringify({
      requested_url: "https://a.example/b",
      failed_audits: [
        {
          id: "render-blocking-resources",
          category: "performance",
          title: "Eliminate render-blocking resources",
          description: "Resources block paint. [Learn more](https://evil.example/)",
          saving_ms: 1200,
          saving_bytes: 0,
          item_count: 1,
          items: [{ url: "https://a.example/site.css", total_bytes: 4000 }],
        },
      ],
      passed_audits: ["uses-text-compression"],
    })
    const content = `[\n${first},\n${second}\n]\n`
    const range = { offset: 2 + first.length + 2, length: second.length }

    const report = pageSpeedReport(content, range, "https://a.example/b")

    expect(report?.failedAudits[0]?.description).toBe("Resources block paint. Learn more")
    expect(report?.passedAudits).toBe(1)
    // A range that names another page's report is refused.
    expect(pageSpeedReport(content, range, "https://a.example/")).toBeNull()
  })
})
