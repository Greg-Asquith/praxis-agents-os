// apps/web/src/features/conversations/components/tools/web/page-speed-report.ts

import type { PageSpeedCategory } from "@/features/conversations/components/tools/web/page-speed-result"
import { isNonNegativeInteger, isRecord } from "@/lib/guards"

type AuditItem = {
  entity: string | null
  label: string | null
  selector: string | null
  snippet: string | null
  totalBytes: number | null
  url: string | null
  wastedBytes: number | null
  wastedMs: number | null
}

export type FailedAudit = {
  category: PageSpeedCategory
  description: string | null
  displayValue: string | null
  id: string
  itemCount: number
  items: AuditItem[]
  savingBytes: number
  savingMs: number
  title: string
}

export type PageSpeedReport = {
  failedAudits: FailedAudit[]
  lcpElement: { label: string | null; selector: string | null; snippet: string | null } | null
  passedAudits: number
  requestedUrl: string
  runWarnings: string[]
  truncated: boolean
}

const MARKDOWN_LINK = /\[([^\]]+)\]\([^)]*\)/g

/**
 * Reads one page's report from the report File's text at the row's range.
 *
 * Every string comes from Google's report of a third-party page, so it renders as text only;
 * Markdown links in descriptions keep their words and drop their addresses.
 */
export function pageSpeedReport(
  content: string,
  range: { length: number; offset: number },
  requestedUrl: string
): PageSpeedReport | null {
  let value: unknown
  try {
    // The File is ASCII JSON, so its byte ranges are character ranges.
    value = JSON.parse(content.slice(range.offset, range.offset + range.length))
  } catch {
    return null
  }
  if (
    !isRecord(value) ||
    value["requested_url"] !== requestedUrl ||
    !Array.isArray(value["failed_audits"])
  )
    return null
  const lcp = isRecord(value["lcp_element"]) ? value["lcp_element"] : null
  return {
    failedAudits: value["failed_audits"].flatMap((audit) => failedAudit(audit) ?? []),
    lcpElement: lcp
      ? {
          label: text(lcp["label"]),
          selector: text(lcp["selector"]),
          snippet: text(lcp["snippet"]),
        }
      : null,
    passedAudits: Array.isArray(value["passed_audits"]) ? value["passed_audits"].length : 0,
    requestedUrl,
    runWarnings: Array.isArray(value["run_warnings"])
      ? value["run_warnings"].flatMap((warning) => text(warning) ?? [])
      : [],
    truncated: value["truncated"] === true,
  }
}

function failedAudit(value: unknown): FailedAudit | null {
  if (!isRecord(value) || typeof value["id"] !== "string") return null
  const category = value["category"]
  if (
    category !== "performance" &&
    category !== "accessibility" &&
    category !== "best_practices" &&
    category !== "seo"
  )
    return null
  const description = text(value["description"])
  return {
    category,
    description: description ? description.replace(MARKDOWN_LINK, "$1") : null,
    displayValue: text(value["display_value"]),
    id: value["id"],
    itemCount: whole(value["item_count"]) ?? 0,
    items: Array.isArray(value["items"])
      ? value["items"].flatMap((item) => auditItem(item) ?? [])
      : [],
    savingBytes: whole(value["saving_bytes"]) ?? 0,
    savingMs: whole(value["saving_ms"]) ?? 0,
    title: text(value["title"]) ?? value["id"],
  }
}

function auditItem(value: unknown): AuditItem | null {
  if (!isRecord(value)) return null
  return {
    entity: text(value["entity"]),
    label: text(value["label"]),
    selector: text(value["selector"]),
    snippet: text(value["snippet"]),
    totalBytes: whole(value["total_bytes"]),
    url: text(value["url"]),
    wastedBytes: whole(value["wasted_bytes"]),
    wastedMs: whole(value["wasted_ms"]),
  }
}

function text(value: unknown): string | null {
  return typeof value === "string" && value ? value : null
}

function whole(value: unknown): number | null {
  return isNonNegativeInteger(value) ? value : null
}
