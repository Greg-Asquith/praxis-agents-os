// apps/web/src/features/conversations/components/tools/web/page-speed-result.ts

import type { DataTableTab } from "@/components/ui/data-table"
import { safeHttpUrl } from "@/components/tool-ui/field-resolution"
import { nodeText } from "@/components/tool-ui/untrusted-node"
import { isNonNegativeInteger, isOneOf, isRecord } from "@/lib/guards"

export const MEASURE_PAGE_SPEED_TOOL_NAME = "measure_page_speed"

const PAGE_SPEED_CATEGORIES = ["performance", "accessibility", "best_practices", "seo"] as const
export type PageSpeedCategory = (typeof PAGE_SPEED_CATEGORIES)[number]
const CATEGORY_SET: ReadonlySet<PageSpeedCategory> = new Set(PAGE_SPEED_CATEGORIES)

export const CATEGORY_LABELS: Record<PageSpeedCategory, string> = {
  accessibility: "Accessibility",
  best_practices: "Best Practices",
  performance: "Performance",
  seo: "SEO",
}

export type Rating = "good" | "needs_improvement" | "poor"
const RATINGS: ReadonlySet<Rating> = new Set(["good", "needs_improvement", "poor"])
export type PageOutcome = Rating | "not_tested"

export const OUTCOMES: Record<
  PageOutcome,
  { badge: "success" | "warning" | "destructive" | "secondary"; label: string }
> = {
  good: { badge: "success", label: "Good" },
  needs_improvement: { badge: "warning", label: "Needs Improvement" },
  poor: { badge: "destructive", label: "Poor" },
  not_tested: { badge: "secondary", label: "Not Tested" },
}

export const PAGE_SPEED_TABS: DataTableTab[] = [
  { id: "all", label: "All", match: () => true },
  ...(Object.keys(OUTCOMES) as PageOutcome[]).map((id) => ({
    hideWhenEmpty: true,
    id,
    label: OUTCOMES[id].label,
    match: (row: Record<string, unknown>) => row["outcome"] === id,
  })),
]

export const METRICS = {
  cls: { label: "CLS", name: "Cumulative Layout Shift", good: 0.1, poor: 0.25 },
  fcp_ms: { label: "FCP", name: "First Contentful Paint", good: 1800, poor: 3000 },
  inp_ms: { label: "INP", name: "Interaction to Next Paint", good: 200, poor: 500 },
  lcp_ms: { label: "LCP", name: "Largest Contentful Paint", good: 2500, poor: 4000 },
  speed_index_ms: { label: "Speed Index", name: "Speed Index", good: 3400, poor: 5800 },
  tbt_ms: { label: "TBT", name: "Total Blocking Time", good: 200, poor: 600 },
  ttfb_ms: { label: "TTFB", name: "Time to First Byte", good: 800, poor: 1800 },
} as const
export type MetricKey = keyof typeof METRICS
export type Strategy = "mobile" | "desktop"

// Lighthouse scores desktop lab runs on tighter curves; CLS and the visitor metrics are the same.
const DESKTOP_BANDS: Partial<Record<MetricKey, { good: number; poor: number }>> = {
  fcp_ms: { good: 934, poor: 1600 },
  lcp_ms: { good: 1200, poor: 2400 },
  speed_index_ms: { good: 1311, poor: 2300 },
  tbt_ms: { good: 150, poor: 350 },
}

const LAB_KEYS = ["lcp_ms", "cls", "tbt_ms", "fcp_ms", "speed_index_ms"] as const
const FIELD_KEYS = ["lcp_ms", "inp_ms", "cls", "ttfb_ms"] as const

export type LabMetrics = Partial<Record<MetricKey, number>>
export type FieldMetric = { p75: number; rating: Rating | null }
export type FieldData = {
  coreWebVitals: "passed" | "failed" | null
  metrics: Partial<Record<MetricKey, FieldMetric>>
}
type TopIssue = { audit: string; savingBytes: number; savingMs: number }

export type PageSpeedRow = {
  errorClass: string | null
  field: FieldData | null
  finalUrl: string | null
  lab: LabMetrics | null
  // The score the row is rated by: performance, or the first category tested without it.
  lead: { category: PageSpeedCategory; score: number } | null
  outcome: PageOutcome
  report: { length: number; offset: number } | null
  requestedUrl: string
  scores: Partial<Record<PageSpeedCategory, number | null>>
  topIssues: TopIssue[]
}

export type PageSpeedResult = {
  categories: PageSpeedCategory[]
  notChecked: number
  origins: Map<string, FieldData>
  reportFileId: string | null
  rows: PageSpeedRow[]
  strategy: Strategy
  tested: number
  testedAt: string
}

export function pageSpeedArgsCount(value: unknown): number | null {
  if (!isRecord(value) || !Array.isArray(value["urls"])) return null
  return value["urls"].length
}

/** Lighthouse's score bands: 90 and up is good, under 50 is poor. */
export function scoreRating(score: number): Rating {
  if (score >= 90) return "good"
  return score >= 50 ? "needs_improvement" : "poor"
}

/** Rates a lab value against Lighthouse's bands for the metric on the device tested. */
export function metricRating(key: MetricKey, value: number, strategy: Strategy): Rating {
  const { good, poor } = (strategy === "desktop" ? DESKTOP_BANDS[key] : undefined) ?? METRICS[key]
  if (value <= good) return "good"
  return value <= poor ? "needs_improvement" : "poor"
}

export function formatMetric(key: MetricKey, value: number): string {
  if (key === "cls") return value.toFixed(2)
  return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${String(Math.round(value))} ms`
}

export function originOf(url: string): string | null {
  try {
    return new URL(url).origin
  } catch {
    return null
  }
}

// The final URL is server-chosen and arrives as an untrusted node; one that isn't http(s) shows as none.
export function pageSpeedResult(value: unknown): PageSpeedResult | null {
  if (!isRecord(value) || !Array.isArray(value["rows"]) || !Array.isArray(value["categories"]))
    return null
  const { not_checked: notChecked, strategy, tested, tested_at: testedAt } = value
  if (
    !isNonNegativeInteger(tested) ||
    !isNonNegativeInteger(notChecked) ||
    typeof testedAt !== "string" ||
    (strategy !== "mobile" && strategy !== "desktop")
  )
    return null
  const categories = value["categories"].filter((item): item is PageSpeedCategory =>
    isOneOf(CATEGORY_SET, item)
  )
  const rows: PageSpeedRow[] = []
  for (const row of value["rows"]) {
    const parsed = pageSpeedRow(row)
    if (parsed === null) return null
    rows.push(parsed)
  }
  const origins = new Map<string, FieldData>()
  if (isRecord(value["origins"])) {
    for (const [origin, data] of Object.entries(value["origins"])) {
      const field = fieldData(data)
      if (field) origins.set(origin, field)
    }
  }
  const file = value["report_file"]
  const reportFileId =
    isRecord(file) && file["entity_kind"] === "file" && typeof file["entity_id"] === "string"
      ? file["entity_id"]
      : null
  return { categories, notChecked, origins, reportFileId, rows, strategy, tested, testedAt }
}

function pageSpeedRow(value: unknown): PageSpeedRow | null {
  if (!isRecord(value) || typeof value["requested_url"] !== "string") return null
  const errorClass = value["error_class"]
  if (errorClass !== null && typeof errorClass !== "string") return null
  const scores: PageSpeedRow["scores"] = {}
  if (isRecord(value["scores"])) {
    for (const category of PAGE_SPEED_CATEGORIES) {
      const score = value["scores"][category]
      if (isNonNegativeInteger(score) || score === null) scores[category] = score
    }
  }
  const report = value["report"]
  const leadCategory = PAGE_SPEED_CATEGORIES.find((category) => scores[category] != null)
  const leadScore = leadCategory ? scores[leadCategory] : null
  const lead =
    leadCategory && leadScore != null ? { category: leadCategory, score: leadScore } : null
  return {
    errorClass,
    field: fieldData(value["field"]),
    finalUrl: safeHttpUrl(nodeText(value["final_url"])),
    lab: labMetrics(value["lab"]),
    lead,
    outcome: errorClass !== null || lead === null ? "not_tested" : scoreRating(lead.score),
    report:
      isRecord(report) &&
      isNonNegativeInteger(report["offset"]) &&
      isNonNegativeInteger(report["length"])
        ? { length: report["length"], offset: report["offset"] }
        : null,
    requestedUrl: value["requested_url"],
    scores,
    topIssues: Array.isArray(value["top_issues"])
      ? value["top_issues"].flatMap((issue) => topIssue(issue) ?? [])
      : [],
  }
}

function labMetrics(value: unknown): LabMetrics | null {
  if (!isRecord(value)) return null
  const lab: LabMetrics = {}
  for (const key of LAB_KEYS) {
    const metric = value[key]
    if (typeof metric === "number" && Number.isFinite(metric) && metric >= 0) lab[key] = metric
  }
  return lab
}

function fieldData(value: unknown): FieldData | null {
  if (!isRecord(value)) return null
  const metrics: FieldData["metrics"] = {}
  for (const key of FIELD_KEYS) {
    const metric = value[key]
    if (!isRecord(metric) || typeof metric["p75"] !== "number") continue
    const rating = metric["rating"]
    metrics[key] = { p75: metric["p75"], rating: isOneOf(RATINGS, rating) ? rating : null }
  }
  const vitals = value["core_web_vitals"]
  return {
    coreWebVitals: vitals === "passed" || vitals === "failed" ? vitals : null,
    metrics,
  }
}

function topIssue(value: unknown): TopIssue | null {
  if (
    !isRecord(value) ||
    typeof value["audit"] !== "string" ||
    !isNonNegativeInteger(value["saving_ms"]) ||
    !isNonNegativeInteger(value["saving_bytes"])
  )
    return null
  return {
    audit: value["audit"],
    savingBytes: value["saving_bytes"],
    savingMs: value["saving_ms"],
  }
}
