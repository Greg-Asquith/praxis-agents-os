// apps/web/src/features/conversations/components/tools/web/check-urls-result.ts

import type { DataTableTab } from "@/components/ui/data-table"
import { safeHttpUrl } from "@/components/tool-ui/field-resolution"
import { nodeText } from "@/components/tool-ui/untrusted-node"
import {
  type WebRedirect,
  webRedirects,
} from "@/features/conversations/components/tools/web/web-redirects"
import { isNonNegativeInteger, isRecord } from "@/lib/guards"

export const CHECK_URLS_TOOL_NAME = "check_urls"

export type CheckedUrlOutcome = "ok" | "redirected" | "broken" | "blocked" | "not_checked"

export const CHECKED_URL_OUTCOMES: Record<
  CheckedUrlOutcome,
  { badge: "success" | "secondary" | "destructive" | "warning"; label: string }
> = {
  ok: { badge: "success", label: "OK" },
  redirected: { badge: "secondary", label: "Redirected" },
  broken: { badge: "destructive", label: "Broken" },
  blocked: { badge: "warning", label: "Blocked" },
  not_checked: { badge: "secondary", label: "Not Checked" },
}

export const CHECKED_URL_TABS: DataTableTab[] = [
  { id: "all", label: "All", match: () => true },
  ...(Object.keys(CHECKED_URL_OUTCOMES) as CheckedUrlOutcome[]).map((id) => ({
    hideWhenEmpty: true,
    id,
    label: CHECKED_URL_OUTCOMES[id].label,
    match: (row: Record<string, unknown>) => row["outcome"] === id,
  })),
]

type CheckedUrl = {
  contentType: string | null
  errorClass: string | null
  finalUrl: string | null
  h1Count: number | null
  outcome: CheckedUrlOutcome
  redirects: WebRedirect[]
  requestedUrl: string
  status: number | null
  timeToFirstByteMs: number | null
  title: string | null
}

export type CheckUrlsResult = {
  checked: number
  checkedAt: string
  notChecked: number
  pageFacts: boolean
  rows: CheckedUrl[]
}

export function checkUrlsArgsCount(value: unknown): number | null {
  if (!isRecord(value) || !Array.isArray(value["urls"])) return null
  return value["urls"].length
}

// Server strings arrive as untrusted nodes; a final URL that isn't http(s) shows as none.
export function checkUrlsResult(value: unknown): CheckUrlsResult | null {
  if (!isRecord(value) || !Array.isArray(value["rows"])) return null
  const { checked, checked_at: checkedAt, not_checked: notChecked } = value
  if (
    !isNonNegativeInteger(checked) ||
    !isNonNegativeInteger(notChecked) ||
    typeof checkedAt !== "string"
  ) {
    return null
  }
  const rows: CheckedUrl[] = []
  for (const row of value["rows"]) {
    const parsed = checkedUrl(row)
    if (parsed === null) return null
    rows.push(parsed)
  }
  const pageFacts = value["rows"].some((row) => isRecord(row) && isRecord(row["page"]))
  return { checked, checkedAt, notChecked, pageFacts, rows }
}

function checkedUrl(value: unknown): CheckedUrl | null {
  if (!isRecord(value) || !Array.isArray(value["redirects"])) return null
  // The agent's own URL, shown as text; an invalid one is a row with error class invalid_url.
  const requestedUrl = value["requested_url"]
  const status = value["status"]
  const errorClass = value["error_class"]
  if (
    typeof requestedUrl !== "string" ||
    (status !== null && !isNonNegativeInteger(status)) ||
    (errorClass !== null && typeof errorClass !== "string")
  ) {
    return null
  }
  const redirects = webRedirects(value["redirects"])
  if (redirects === null) return null
  const page = isRecord(value["page"]) ? value["page"] : null
  const ttfb = value["time_to_first_byte_ms"]
  return {
    contentType: nodeText(value["content_type"]),
    errorClass,
    finalUrl: safeHttpUrl(nodeText(value["final_url"])),
    h1Count: page && isNonNegativeInteger(page["h1_count"]) ? page["h1_count"] : null,
    outcome: outcome(status, errorClass, value["blocked_by_site"] === true, redirects.length),
    redirects,
    requestedUrl,
    status,
    timeToFirstByteMs: isNonNegativeInteger(ttfb) ? ttfb : null,
    title: page ? nodeText(page["title"]) : null,
  }
}

function outcome(
  status: number | null,
  errorClass: string | null,
  blockedBySite: boolean,
  redirects: number
): CheckedUrlOutcome {
  if (errorClass === "not_checked") return "not_checked"
  if (blockedBySite) return "blocked"
  if (errorClass !== null || status === null || status >= 400) return "broken"
  return redirects > 0 ? "redirected" : "ok"
}
