// apps/web/src/integrations/google_search_console/lib/inspection-model.ts

import { isUntrustedNode, type UntrustedNode } from "@/components/tool-ui/untrusted-node"
import { isRecord } from "@/lib/guards"

type SearchConsoleRichResult = {
  type: string
  issueCount: number
}

export type SearchConsoleInspection = {
  url: string
  verdict: string
  coverageState: string
  robotsTxtState: string
  indexingState: string
  pageFetchState: string
  crawledAs: string
  lastCrawlTime: string
  googleCanonical: UntrustedNode | null
  userCanonical: UntrustedNode | null
  sitemap: UntrustedNode[]
  referringUrls: UntrustedNode[]
  mobileUsabilityVerdict: string
  richResultsVerdict: string
  richResults: SearchConsoleRichResult[]
  inspectionResultLink: string
  errorCode: string | null
  message: UntrustedNode | null
}

const STRING_FIELDS = [
  "url",
  "verdict",
  "coverage_state",
  "robots_txt_state",
  "indexing_state",
  "page_fetch_state",
  "crawled_as",
  "last_crawl_time",
  "mobile_usability_verdict",
  "rich_results_verdict",
  "inspection_result_link",
] as const

export function parseInspectionData(value: unknown): SearchConsoleInspection[] | null {
  if (!isRecord(value) || !Array.isArray(value["inspections"])) return null
  const inspections: SearchConsoleInspection[] = []
  for (const item of value["inspections"]) {
    const inspection = parseInspection(item)
    if (!inspection) return null
    inspections.push(inspection)
  }
  return inspections
}

function parseInspection(value: unknown): SearchConsoleInspection | null {
  if (
    !isRecord(value) ||
    !isStringFields(value, STRING_FIELDS) ||
    !isValidOptionalTimestamp(value.last_crawl_time) ||
    !isOptionalNode(value["google_canonical"]) ||
    !isOptionalNode(value["user_canonical"]) ||
    !isNodeList(value["sitemap"]) ||
    !isNodeList(value["referring_urls"]) ||
    !Array.isArray(value["rich_results"]) ||
    (value["error_code"] !== null && typeof value["error_code"] !== "string") ||
    (value["message"] !== null && !isUntrustedNode(value["message"]))
  ) {
    return null
  }
  const richResults: SearchConsoleRichResult[] = []
  for (const item of value["rich_results"]) {
    if (
      !isRecord(item) ||
      typeof item["type"] !== "string" ||
      typeof item["issue_count"] !== "number"
    ) {
      return null
    }
    richResults.push({ type: item["type"], issueCount: item["issue_count"] })
  }
  return {
    url: value.url,
    verdict: value.verdict,
    coverageState: value.coverage_state,
    robotsTxtState: value.robots_txt_state,
    indexingState: value.indexing_state,
    pageFetchState: value.page_fetch_state,
    crawledAs: value.crawled_as,
    lastCrawlTime: value.last_crawl_time,
    googleCanonical: value["google_canonical"],
    userCanonical: value["user_canonical"],
    sitemap: value["sitemap"],
    referringUrls: value["referring_urls"],
    mobileUsabilityVerdict: value.mobile_usability_verdict,
    richResultsVerdict: value.rich_results_verdict,
    richResults,
    inspectionResultLink: value.inspection_result_link,
    errorCode: value["error_code"],
    message: value["message"],
  }
}

function isValidOptionalTimestamp(value: string): boolean {
  return value === "" || !Number.isNaN(Date.parse(value))
}

function isStringFields<Key extends string>(
  value: Record<string, unknown>,
  keys: readonly Key[]
): value is Record<string, unknown> & Record<Key, string> {
  return keys.every((key) => typeof value[key] === "string")
}

function isOptionalNode(value: unknown): value is UntrustedNode | null {
  return value === null || isUntrustedNode(value)
}

function isNodeList(value: unknown): value is UntrustedNode[] {
  return Array.isArray(value) && value.length <= 20 && value.every(isUntrustedNode)
}
