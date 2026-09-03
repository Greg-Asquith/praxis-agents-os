// apps/web/src/integrations/google_ads/presenters/update-positive-keyword-status.tsx

import { ArrowRightIcon } from "lucide-react"

import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { Stat, StatGroup } from "@/components/ui/stat"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type { EditedValue } from "@/components/tool-ui/edited-values"
import {
  parsePositiveKeywordReference,
  type PositiveKeywordReference,
  type PositiveKeywordStatus,
} from "@/integrations/google_ads/lib/positive-keywords"
import {
  createGoogleAdsWritePresenter,
  defineGoogleAdsWriteVariant,
} from "@/integrations/google_ads/presenters/write-presenter"
import { titleCaseToken } from "@/lib/format"
import { isNonNegativeInteger, isNullableString, isRecord } from "@/lib/guards"

const OUTCOMES = ["updated", "already_set", "failed", "unverified"] as const
type KeywordStatusOutcome = (typeof OUTCOMES)[number]
const STATUS_LABELS: Record<PositiveKeywordStatus, string> = {
  ENABLED: "Enabled",
  PAUSED: "Paused",
}

type KeywordStatusArgs = {
  keywords: PositiveKeywordReference[]
  statuses: KeywordStatusSelection[]
}

type KeywordStatusSelection = { status: PositiveKeywordStatus }

type KeywordStatusRow = {
  errorCode: string | null
  message: string | null
  outcome: KeywordStatusOutcome
  previousStatus: PositiveKeywordStatus
  reference: PositiveKeywordReference
  requestedStatus: PositiveKeywordStatus
}

type KeywordStatusResult = {
  counts: Record<KeywordStatusOutcome, number>
  rows: KeywordStatusRow[]
  samplesTruncated: boolean
}

const COLUMNS: DataColumn[] = [
  { key: "scope", kind: "text", label: "Campaign · Ad Group" },
  { key: "keyword", kind: "text", label: "Keyword" },
  { key: "matchType", kind: "text", label: "Match Type" },
  { key: "previous", kind: "status", label: "Before" },
  { key: "requested", kind: "status", label: "After" },
  { key: "outcome", kind: "status", label: "Outcome" },
  { key: "details", kind: "text", label: "Details", width: 280 },
]

export const googleAdsUpdatePositiveKeywordStatusPresenter = createGoogleAdsWritePresenter({
  key: "google-ads-update-positive-keyword-status",
  variants: {
    google_ads_update_keyword_status: defineGoogleAdsWriteVariant({
      approval: {
        approveLabel: "Approve & Update",
        label: "Update Google Ads Keyword Status",
        parseArgs: keywordStatusArgs,
        prompt:
          "Review every selected keyword and its proposed status before changing ad delivery.",
        renderFields: false,
        renderSummary: (value, fallback, onFieldEdit, disabled) =>
          renderApprovalSummary(keywordStatusArgs(value) ?? fallback, onFieldEdit, disabled),
        title: "Update Keyword Status",
      },
      deniedDescription: "This keyword status update was declined. Nothing was changed.",
      details: (args) => (args ? [{ label: "Keywords", value: String(args.keywords.length) }] : []),
      emptyLabel: "No Google Ads accounts updated keyword status.",
      failedDescription: "The update did not finish. No keyword status change was confirmed.",
      heading: "Update Keyword Status",
      malformedDescription:
        "The system couldn't verify this account's keyword status outcomes. Check Google Ads before taking further action.",
      parseResult: keywordStatusResult,
      progressLabel: "Updating Google Ads keyword status…",
      renderOutcome,
      resultAriaLabel: "Google Ads positive keyword status results",
      resultFailure:
        "The system couldn't verify the keyword status changes. Check Google Ads before taking further action.",
      unconfirmedAriaLabel: "Unconfirmed Google Ads keyword status update",
      unverifiedDescription:
        "The system couldn't verify whether Google Ads applied these keyword status changes. Check Google Ads before retrying.",
      waitingLabel: "Waiting for keyword status approval…",
    }),
  },
})

function renderApprovalSummary(
  args: KeywordStatusArgs,
  onFieldEdit: (key: string, value: EditedValue) => void,
  disabled: boolean
) {
  return (
    <section aria-label="Proposed keyword status changes" className="grid gap-1.5">
      {args.keywords.map((keyword, index) => (
        <div
          className="border-border/80 bg-card grid min-w-0 gap-3 rounded-lg border px-3 py-3 shadow-xs sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
          key={keyword.identity}
        >
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{keyword.text}</p>
            <p className="text-muted-foreground mt-0.5 truncate text-xs">
              {keyword.scopeLabel} · {titleCaseToken(keyword.matchType, keyword.matchType)}
            </p>
          </div>
          {renderStatusEditor(keyword, index, args.statuses, onFieldEdit, disabled)}
        </div>
      ))}
    </section>
  )
}

function renderStatusEditor(
  keyword: PositiveKeywordReference,
  index: number,
  statuses: KeywordStatusSelection[],
  onFieldEdit: (key: string, value: EditedValue) => void,
  disabled: boolean
) {
  const requested = statuses[index]?.status
  if (requested === undefined) return null
  return (
    <div
      aria-label={`${STATUS_LABELS[keyword.status]} before, ${STATUS_LABELS[requested]} after`}
      className="border-border bg-muted/25 grid grid-cols-[auto_auto_minmax(7rem,9rem)] items-center gap-2 rounded-md border px-3 py-2 text-sm"
    >
      <span>{STATUS_LABELS[keyword.status]}</span>
      <ArrowRightIcon aria-hidden="true" className="text-muted-foreground size-3.5" />
      <Select
        disabled={disabled}
        onValueChange={(nextStatus) => {
          if (nextStatus === "ENABLED" || nextStatus === "PAUSED") {
            const editedStatuses = statuses.map((selection, statusIndex) =>
              statusIndex === index ? { status: nextStatus } : selection
            )
            onFieldEdit("statuses", editedStatuses)
          }
        }}
        value={requested}
      >
        <SelectTrigger
          aria-label={`Requested status for ${keyword.text} in ${keyword.scopeLabel}`}
          className="h-8"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="ENABLED">Enabled</SelectItem>
          <SelectItem value="PAUSED">Paused</SelectItem>
        </SelectContent>
      </Select>
    </div>
  )
}

function renderOutcome(result: KeywordStatusResult) {
  const rows = result.rows.map<DataRow>((row) => ({
    details:
      [row.message, row.errorCode ? titleCaseToken(row.errorCode, row.errorCode) : null]
        .filter((value): value is string => Boolean(value))
        .join(" · ") || "—",
    keyword: row.reference.text,
    matchType: titleCaseToken(row.reference.matchType, row.reference.matchType),
    outcome:
      row.outcome === "already_set" ? "Already set" : titleCaseToken(row.outcome, row.outcome),
    previous: STATUS_LABELS[row.previousStatus],
    requested: STATUS_LABELS[row.requestedStatus],
    scope: row.reference.scopeLabel,
  }))
  return (
    <DataTable
      columns={COLUMNS}
      exportFilename="google-ads-keyword-status.csv"
      header={
        <StatGroup className="px-3 pt-2">
          <Stat
            label="Updated"
            tone={result.counts.updated > 0 ? "success" : undefined}
            value={result.counts.updated}
          />
          <Stat label="Already set" value={result.counts.already_set} />
          <Stat
            label="Failed"
            tone={result.counts.failed > 0 ? "danger" : undefined}
            value={result.counts.failed}
          />
          <Stat
            label="Unverified"
            tone={result.counts.unverified > 0 ? "warning" : undefined}
            value={result.counts.unverified}
          />
        </StatGroup>
      }
      pageSize={25}
      rows={rows}
      truncationNote={
        result.samplesTruncated
          ? "The table contains a representative sample. Complete evidence is available in the Audit Log."
          : null
      }
    />
  )
}

function keywordStatusArgs(value: unknown): KeywordStatusArgs | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["keywords"]) ||
    value["keywords"].length < 1 ||
    value["keywords"].length > 500 ||
    !Array.isArray(value["statuses"]) ||
    value["statuses"].length !== value["keywords"].length
  )
    return null
  const keywords: PositiveKeywordReference[] = []
  const identities = new Set<string>()
  for (const item of value["keywords"]) {
    const keyword = parsePositiveKeywordReference(item)
    if (!keyword) return null
    if (identities.has(keyword.identity)) return null
    identities.add(keyword.identity)
    keywords.push(keyword)
  }
  const statuses: KeywordStatusSelection[] = []
  for (const item of value["statuses"]) {
    if (
      !isRecord(item) ||
      Object.keys(item).length !== 1 ||
      (item["status"] !== "ENABLED" && item["status"] !== "PAUSED")
    ) {
      return null
    }
    statuses.push({ status: item["status"] })
  }
  return { keywords, statuses }
}

function keywordStatusResult(value: unknown): KeywordStatusResult | null {
  if (
    !isRecord(value) ||
    !isRecord(value["counts"]) ||
    !isRecord(value["samples"]) ||
    typeof value["samples_truncated"] !== "boolean"
  )
    return null
  const counts = {} as Record<KeywordStatusOutcome, number>
  const rows: KeywordStatusRow[] = []
  for (const outcome of OUTCOMES) {
    const count = value["counts"][outcome]
    const samples = value["samples"][outcome]
    if (!isNonNegativeInteger(count) || !Array.isArray(samples)) return null
    counts[outcome] = count
    for (const sample of samples) {
      const row = parseResultRow(sample, outcome)
      if (!row) return null
      rows.push(row)
    }
  }
  const totalCount = OUTCOMES.reduce((total, outcome) => total + counts[outcome], 0)
  if (!value["samples_truncated"] && rows.length !== totalCount) return null
  return { counts, rows, samplesTruncated: value["samples_truncated"] }
}

function parseResultRow(value: unknown, outcome: KeywordStatusOutcome): KeywordStatusRow | null {
  if (!isRecord(value)) return null
  const reference = parsePositiveKeywordReference(value["keyword"])
  const previousStatus = value["previous_status"]
  const requestedStatus = value["requested_status"]
  if (
    !reference ||
    value["outcome"] !== outcome ||
    (previousStatus !== "ENABLED" && previousStatus !== "PAUSED") ||
    (requestedStatus !== "ENABLED" && requestedStatus !== "PAUSED") ||
    !isNullableString(value["external_ref"]) ||
    !isNullableString(value["error_code"]) ||
    !isNullableString(value["message"])
  )
    return null
  const successful = outcome === "updated" || outcome === "already_set"
  if (
    reference.status !== (successful ? requestedStatus : previousStatus) ||
    (outcome === "already_set" && previousStatus !== requestedStatus) ||
    (outcome !== "already_set" && previousStatus === requestedStatus)
  )
    return null
  return {
    errorCode: value["error_code"],
    message: value["message"],
    outcome,
    previousStatus,
    reference,
    requestedStatus,
  }
}
