// apps/web/src/integrations/google_search_console/presenters/submit-sitemap.tsx

import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { Stat, StatGroup } from "@/components/ui/stat"
import {
  createGoogleSearchConsoleWritePresenter,
  defineGoogleSearchConsoleWriteVariant,
} from "@/integrations/google_search_console/presenters/write-presenter"
import { isDateTimeString, isNonNegativeInteger, isNullableString, isRecord } from "@/lib/guards"

const OUTCOMES = ["submitted", "failed", "unverified"] as const
const ERROR_CODES = ["rejected", "unverified", "status_unavailable"] as const
type SitemapOutcome = (typeof OUTCOMES)[number]

type SubmissionHint = {
  previouslySubmitted: boolean
  sitemapUrl: string
  siteUrl: string
}

type SubmissionArgs = {
  hints: SubmissionHint[]
  sitemapUrls: string[]
  writableSites: string[]
}

type SubmissionRow = {
  errorCode: string | null
  errors: number | null
  isPending: boolean | null
  lastSubmitted: string | null
  message: string | null
  outcome: SitemapOutcome
  previouslySubmitted: boolean
  sitemapUrl: string
  statusRead: boolean
  warnings: number | null
}

type SubmissionResult = {
  failedCount: number
  rows: SubmissionRow[]
  submittedCount: number
}

const COLUMNS: DataColumn[] = [
  { key: "sitemap", kind: "link", label: "Sitemap", width: "auto" },
  { key: "action", kind: "badge", label: "Action" },
  { key: "lastSubmitted", kind: "datetime", label: "Submitted" },
  { key: "processing", kind: "status", label: "Google status" },
  { key: "warnings", kind: "number", label: "Warnings", isMetric: true },
  { key: "errors", kind: "number", label: "Errors", isMetric: true },
  { key: "outcome", kind: "status", label: "Outcome" },
  { key: "details", kind: "text", label: "Details" },
]

export const submitSitemapPresenter = createGoogleSearchConsoleWritePresenter({
  key: "google-search-console-submit-sitemap",
  variants: {
    google_search_console_submit_sitemap: defineGoogleSearchConsoleWriteVariant({
      approval: {
        approveLabel: "Approve & Submit",
        label: "Submit Search Console Sitemaps",
        parseArgs: submissionArgs,
        prompt:
          "The agent wants Google to re-process these sitemaps. Google decides when and whether to crawl the URLs they list.",
        renderSummary: renderApprovalSummary,
        title: "Submit Sitemaps to Google Search Console",
        validateArgs: validateSubmissionArgs,
      },
      deniedDescription: "This sitemap submission was declined. Nothing was submitted.",
      details: (args) =>
        args ? [{ label: "Sitemaps", value: String(args.sitemapUrls.length) }] : [],
      emptyLabel: "No Search Console sites submitted sitemaps.",
      failedDescription: "The submission did not finish. No sitemap submission was confirmed.",
      heading: "Submit Search Console Sitemaps",
      malformedDescription:
        "The system couldn't verify this site's sitemap outcomes. Check the sitemaps in Search Console before submitting again.",
      parseResult: submissionResult,
      progressLabel: "Submitting Search Console sitemaps…",
      renderOutcome: renderSubmissionOutcome,
      resultAriaLabel: "Search Console sitemap submission results",
      resultFailure:
        "The system couldn't verify the sitemap submissions. Check Search Console before submitting again.",
      unconfirmedAriaLabel: "Unconfirmed Search Console sitemap submission",
      unverifiedDescription:
        "Google may or may not have received the submission. Check the sitemap in Search Console before submitting again.",
      waitingLabel: "Waiting for sitemap submission approval…",
    }),
  },
})

function renderApprovalSummary(args: SubmissionArgs) {
  const hints = new Map(args.hints.map((hint) => [hint.sitemapUrl, hint]))
  return (
    <section aria-label="Sitemaps selected for submission" className="grid gap-1.5">
      {args.sitemapUrls.map((sitemapUrl) => {
        const hint = hints.get(sitemapUrl)
        return (
          <div
            className="border-border/80 bg-card flex min-w-0 items-center gap-2 rounded-lg border px-3 py-2.5 shadow-xs"
            key={sitemapUrl}
          >
            {hint ? (
              <Badge variant={hint.previouslySubmitted ? "outline" : "secondary"}>
                {hint.previouslySubmitted ? "Resubmit" : "Add"}
              </Badge>
            ) : null}
            <span className="min-w-0 truncate text-sm" title={sitemapUrl}>
              {sitemapUrl}
            </span>
          </div>
        )
      })}
    </section>
  )
}

function renderSubmissionOutcome(result: SubmissionResult) {
  const rows = result.rows.map<DataRow>((row) => ({
    action: row.previouslySubmitted ? "Resubmit" : "Add",
    details: row.message ?? humanizeErrorCode(row.errorCode) ?? "—",
    errors: row.errors,
    lastSubmitted: row.lastSubmitted,
    outcome: outcomeLabel(row.outcome),
    processing: row.statusRead ? (row.isPending ? "Pending" : "Processed") : "Status unavailable",
    sitemap: row.sitemapUrl,
    warnings: row.warnings,
  }))
  const unverifiedCount = result.rows.filter((row) => row.outcome === "unverified").length
  return (
    <DataTable
      columns={COLUMNS}
      exportFilename="search-console-sitemap-submissions.csv"
      header={
        <StatGroup className="px-3 pt-2">
          <Stat
            label="Submitted"
            tone={result.submittedCount > 0 ? "success" : undefined}
            value={result.submittedCount}
          />
          <Stat
            label="Failed"
            tone={result.failedCount > 0 ? "danger" : undefined}
            value={result.failedCount}
          />
          <Stat
            label="Unverified"
            tone={unverifiedCount > 0 ? "warning" : undefined}
            value={unverifiedCount}
          />
        </StatGroup>
      }
      pageSize={20}
      rows={rows}
    />
  )
}

function submissionArgs(value: unknown): SubmissionArgs | null {
  if (!isRecord(value) || !Array.isArray(value["sitemap_urls"])) return null
  const sitemapUrls = normalizedUrls(value["sitemap_urls"])
  if (!sitemapUrls) return null
  const hints = submissionHints(value["_sitemap_submission_status"])
  if (value["_sitemap_submission_status"] !== undefined && hints === null) return null
  const writableSites = submissionWritableSites(value["_sitemap_writable_sites"])
  if (writableSites === null) return null
  return { hints: hints ?? [], sitemapUrls, writableSites }
}

function normalizedUrls(value: unknown[]): string[] | null {
  if (value.length < 1 || value.length > 20) return null
  const urls: string[] = []
  const seen = new Set<string>()
  for (const item of value) {
    if (typeof item !== "string") return null
    const url = item.trim()
    if (!validHttpUrl(url) || seen.has(url)) return null
    seen.add(url)
    urls.push(url)
  }
  return urls
}

function submissionHints(value: unknown): SubmissionHint[] | null {
  if (value === undefined) return []
  if (!Array.isArray(value)) return null
  const hints: SubmissionHint[] = []
  for (const item of value) {
    if (
      !isRecord(item) ||
      typeof item["sitemap_url"] !== "string" ||
      typeof item["site_url"] !== "string" ||
      typeof item["previously_submitted"] !== "boolean"
    ) {
      return null
    }
    hints.push({
      previouslySubmitted: item["previously_submitted"],
      sitemapUrl: item["sitemap_url"],
      siteUrl: item["site_url"],
    })
  }
  return hints
}

function submissionWritableSites(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.length < 1 || value.length > 20) return null
  const sites = value.filter((site): site is string => typeof site === "string" && site.length > 0)
  return sites.length === value.length && new Set(sites).size === sites.length ? sites : null
}

function validateSubmissionArgs(value: unknown): string | null {
  const args = submissionArgs(value)
  if (!args) return "Enter between one and 20 unique HTTP or HTTPS sitemap URLs."
  if (args.sitemapUrls.some((url) => !args.writableSites.some((site) => matchesSite(url, site)))) {
    return "Each sitemap URL must belong to one of the selected writable Search Console sites."
  }
  return null
}

function submissionResult(value: unknown): SubmissionResult | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["sitemaps"]) ||
    !isNonNegativeInteger(value["submitted_count"]) ||
    !isNonNegativeInteger(value["failed_count"])
  ) {
    return null
  }
  const rows = value["sitemaps"].map(submissionRow)
  if (rows.some((row) => row === null)) return null
  const parsedRows = rows as SubmissionRow[]
  const submittedCount = parsedRows.filter((row) => row.outcome === "submitted").length
  const failedCount = parsedRows.filter((row) => row.outcome === "failed").length
  if (value["submitted_count"] !== submittedCount || value["failed_count"] !== failedCount) {
    return null
  }
  return {
    failedCount: value["failed_count"],
    rows: parsedRows,
    submittedCount: value["submitted_count"],
  }
}

function submissionRow(value: unknown): SubmissionRow | null {
  if (
    !isRecord(value) ||
    typeof value["sitemap_url"] !== "string" ||
    !OUTCOMES.some((outcome) => value["outcome"] === outcome) ||
    typeof value["previously_submitted"] !== "boolean" ||
    typeof value["status_read"] !== "boolean" ||
    !isNullableString(value["last_submitted"] ?? null) ||
    !nullableErrorCode(value["error_code"] ?? null) ||
    !isNullableString(value["message"] ?? null) ||
    !nullableBoolean(value["is_pending"]) ||
    !nullableNonNegativeInteger(value["warnings"]) ||
    !nullableNonNegativeInteger(value["errors"])
  ) {
    return null
  }
  const lastSubmitted = typeof value["last_submitted"] === "string" ? value["last_submitted"] : null
  if (lastSubmitted !== null && !isDateTimeString(lastSubmitted)) return null
  if (
    value["status_read"] &&
    (typeof value["is_pending"] !== "boolean" ||
      !isNonNegativeInteger(value["warnings"]) ||
      !isNonNegativeInteger(value["errors"]))
  ) {
    return null
  }
  return {
    errorCode: typeof value["error_code"] === "string" ? value["error_code"] : null,
    errors: typeof value["errors"] === "number" ? value["errors"] : null,
    isPending: typeof value["is_pending"] === "boolean" ? value["is_pending"] : null,
    lastSubmitted,
    message: typeof value["message"] === "string" ? value["message"] : null,
    outcome: value["outcome"] as SitemapOutcome,
    previouslySubmitted: value["previously_submitted"],
    sitemapUrl: value["sitemap_url"],
    statusRead: value["status_read"],
    warnings: typeof value["warnings"] === "number" ? value["warnings"] : null,
  }
}

function nullableErrorCode(value: unknown): boolean {
  return value === null || ERROR_CODES.some((errorCode) => value === errorCode)
}

function validHttpUrl(value: string): boolean {
  try {
    const url = new URL(value)
    return (url.protocol === "http:" || url.protocol === "https:") && !url.username && !url.password
  } catch {
    return false
  }
}

function matchesSite(value: string, site: string): boolean {
  const url = new URL(value)
  if (site.startsWith("sc-domain:")) {
    const domain = site.slice("sc-domain:".length).toLowerCase()
    return (
      url.hostname.toLowerCase() === domain || url.hostname.toLowerCase().endsWith(`.${domain}`)
    )
  }
  try {
    const prefix = new URL(site)
    return url.origin === prefix.origin && url.pathname.startsWith(prefix.pathname)
  } catch {
    return false
  }
}

function nullableBoolean(value: unknown): boolean {
  return value === null || value === undefined || typeof value === "boolean"
}

function nullableNonNegativeInteger(value: unknown): boolean {
  return value === null || value === undefined || isNonNegativeInteger(value)
}

function outcomeLabel(value: SitemapOutcome): string {
  return value === "submitted" ? "Submitted" : value === "unverified" ? "Unverified" : "Failed"
}

function humanizeErrorCode(value: string | null): string | null {
  return value
    ? value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase())
    : null
}
