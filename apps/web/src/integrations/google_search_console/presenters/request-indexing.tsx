// apps/web/src/integrations/google_search_console/presenters/request-indexing.tsx

import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { Stat, StatGroup } from "@/components/ui/stat"
import {
  isValidHttpUrl,
  matchesWritableSite,
  parseWritableSiteUrls,
} from "@/integrations/google_search_console/lib/write-args"
import {
  createGoogleSearchConsoleWritePresenter,
  defineGoogleSearchConsoleWriteVariant,
} from "@/integrations/google_search_console/presenters/write-presenter"
import { titleCaseToken } from "@/lib/format"
import { isDateTimeString, isNonNegativeInteger, isNullableString, isRecord } from "@/lib/guards"

const NOTIFICATION_TYPES = ["URL_UPDATED", "URL_DELETED"] as const
const PAGE_TYPES = ["job_posting", "broadcast_event"] as const
const OUTCOMES = ["notified", "failed", "unverified"] as const
const ERROR_CODES = [
  "not_owner",
  "scope_missing",
  "api_not_enabled",
  "quota_exhausted",
  "rejected",
  "unverified",
  "status_unavailable",
] as const

type NotificationType = (typeof NOTIFICATION_TYPES)[number]
type PageType = (typeof PAGE_TYPES)[number]
type IndexingOutcome = (typeof OUTCOMES)[number]

type Notification = {
  notificationType: NotificationType
  pageType: PageType
  url: string
}

type IndexingArgs = {
  notifications: Notification[]
  writableSites: string[]
}

type IndexingRow = Notification & {
  errorCode: (typeof ERROR_CODES)[number] | null
  message: string | null
  notifyTime: string | null
  outcome: IndexingOutcome
}

type IndexingResult = {
  failedCount: number
  notifiedCount: number
  rows: IndexingRow[]
}

const COLUMNS: DataColumn[] = [
  { key: "url", kind: "link", label: "URL", width: "auto" },
  { key: "notification", kind: "badge", label: "Notification" },
  { key: "pageType", kind: "badge", label: "Eligible page type" },
  { key: "notifyTime", kind: "datetime", label: "Sent" },
  { key: "outcome", kind: "status", label: "Outcome" },
  { key: "details", kind: "text", label: "Details" },
]

export const requestIndexingPresenter = createGoogleSearchConsoleWritePresenter({
  key: "google-search-console-request-indexing",
  variants: {
    google_search_console_request_indexing: defineGoogleSearchConsoleWriteVariant({
      approval: {
        approveLabel: "Approve & Notify",
        label: "Send Search Console Indexing Notifications",
        parseArgs: indexingArgs,
        prompt:
          "Google accepts these notifications only for job posting pages and livestream video pages. Notifications for other pages are ignored and may violate Google's guidelines. A URL_DELETED notification asks Google to remove the page from its index. Before approving one, confirm that the page returns 404 or 410, or includes a noindex directive. Google decides when and whether to crawl, index, or remove each page.",
        title: "Send Indexing API Notifications",
        validateArgs: validateIndexingArgs,
      },
      deniedDescription: "These Indexing API notifications were declined. Nothing was sent.",
      details: (args) =>
        args ? [{ label: "Notifications", value: String(args.notifications.length) }] : [],
      emptyLabel: "No Search Console sites sent Indexing API notifications.",
      failedDescription: "The notifications did not finish. No Indexing API action was confirmed.",
      heading: "Send Search Console Indexing Notifications",
      malformedDescription:
        "The system couldn't verify this site's Indexing API outcomes. Check Search Console before trying again.",
      parseResult: indexingResult,
      progressLabel: "Sending Search Console indexing notifications…",
      renderOutcome: renderIndexingOutcome,
      resultAriaLabel: "Search Console Indexing API notification results",
      resultFailure:
        "The system couldn't verify the Indexing API notifications. Check Search Console before trying again.",
      unconfirmedAriaLabel: "Unconfirmed Search Console Indexing API notification",
      unverifiedDescription:
        "Google may or may not have received the notification. Check Search Console before trying again.",
      waitingLabel: "Waiting for Indexing API notification approval…",
    }),
  },
})

function renderIndexingOutcome(result: IndexingResult) {
  const rows = result.rows.map<DataRow>((row) => ({
    details: row.message ?? errorDescription(row.errorCode),
    notification: row.notificationType === "URL_UPDATED" ? "Updated" : "Deleted",
    notifyTime: row.notifyTime,
    outcome: titleCaseToken(row.outcome, row.outcome),
    pageType: row.pageType === "job_posting" ? "Job posting" : "Livestream video",
    url: row.url,
  }))
  const unverifiedCount = result.rows.filter((row) => row.outcome === "unverified").length
  return (
    <DataTable
      columns={COLUMNS}
      exportFilename="search-console-indexing-notifications.csv"
      header={
        <StatGroup className="px-3 pt-2">
          <Stat
            label="Notified"
            tone={result.notifiedCount > 0 ? "success" : undefined}
            value={result.notifiedCount}
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

function indexingArgs(value: unknown): IndexingArgs | null {
  if (!isRecord(value) || !Array.isArray(value["notifications"])) return null
  const notifications = normalizedNotifications(value["notifications"])
  const writableSites = parseWritableSiteUrls(value["_indexing_writable_sites"])
  return notifications && writableSites ? { notifications, writableSites } : null
}

function normalizedNotifications(value: unknown[]): Notification[] | null {
  if (value.length < 1 || value.length > 20) return null
  const notifications: Notification[] = []
  const seen = new Set<string>()
  for (const item of value) {
    if (
      !isRecord(item) ||
      typeof item["url"] !== "string" ||
      !NOTIFICATION_TYPES.some((type) => item["notification_type"] === type) ||
      !PAGE_TYPES.some((type) => item["page_type"] === type)
    ) {
      return null
    }
    const url = item["url"].trim()
    if (!isValidHttpUrl(url) || seen.has(url)) return null
    seen.add(url)
    notifications.push({
      notificationType: item["notification_type"] as NotificationType,
      pageType: item["page_type"] as PageType,
      url,
    })
  }
  return notifications
}

function validateIndexingArgs(value: unknown): string | null {
  const args = indexingArgs(value)
  if (!args) {
    return "Enter between one and 20 unique HTTP or HTTPS URLs with an eligible page type and notification."
  }
  if (
    args.notifications.some(
      ({ url }) => !args.writableSites.some((site) => matchesWritableSite(url, site))
    )
  ) {
    return "Each URL must belong to one of the selected writable Search Console sites."
  }
  return null
}

function indexingResult(value: unknown): IndexingResult | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["notifications"]) ||
    !isNonNegativeInteger(value["notified_count"]) ||
    !isNonNegativeInteger(value["failed_count"])
  ) {
    return null
  }
  const rows = value["notifications"].map(indexingRow)
  if (rows.some((row) => row === null)) return null
  const parsedRows = rows as IndexingRow[]
  const notifiedCount = parsedRows.filter((row) => row.outcome === "notified").length
  const failedCount = parsedRows.filter((row) => row.outcome === "failed").length
  if (value["notified_count"] !== notifiedCount || value["failed_count"] !== failedCount) {
    return null
  }
  return { failedCount, notifiedCount, rows: parsedRows }
}

function indexingRow(value: unknown): IndexingRow | null {
  if (!isRecord(value)) return null
  const errorCode = value["error_code"] ?? null
  const message = value["message"] ?? null
  const notifyTimeValue = value["notify_time"] ?? null
  if (
    typeof value["url"] !== "string" ||
    !NOTIFICATION_TYPES.some((type) => value["notification_type"] === type) ||
    !PAGE_TYPES.some((type) => value["page_type"] === type) ||
    !OUTCOMES.some((outcome) => value["outcome"] === outcome) ||
    (errorCode !== null && !ERROR_CODES.some((candidate) => errorCode === candidate)) ||
    !isNullableString(message) ||
    !isNullableString(notifyTimeValue)
  ) {
    return null
  }
  const notifyTime = typeof notifyTimeValue === "string" ? notifyTimeValue : null
  if (notifyTime !== null && !isDateTimeString(notifyTime)) return null
  return {
    errorCode: typeof errorCode === "string" ? (errorCode as IndexingRow["errorCode"]) : null,
    message: typeof message === "string" ? message : null,
    notificationType: value["notification_type"] as NotificationType,
    notifyTime,
    outcome: value["outcome"] as IndexingOutcome,
    pageType: value["page_type"] as PageType,
    url: value["url"],
  }
}

function errorDescription(value: IndexingRow["errorCode"]): string {
  switch (value) {
    case null:
      return "—"
    case "quota_exhausted":
      return "The Google Cloud project has reached the limit of 200 notifications per day."
    case "not_owner":
      return "Grant the connected account Owner permission for this Search Console property."
    case "scope_missing":
      return "Reconnect Google Search Console to grant the Indexing API permission."
    case "api_not_enabled":
      return "Enable the Indexing API in the Google Cloud project, then try again."
    case "status_unavailable":
      return "Google accepted the notification, but its status could not be read."
    case "unverified":
      return "Google may or may not have received the notification. Check Search Console before trying again."
    case "rejected":
      return "Google rejected the notification. Check the URL and its eligible page type."
  }
}
