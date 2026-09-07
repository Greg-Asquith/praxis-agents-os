// apps/web/src/integrations/google_ads/presenters/remove-positive-keywords.tsx

import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { Stat, StatGroup } from "@/components/ui/stat"
import {
  createGoogleAdsWritePresenter,
  defineGoogleAdsWriteVariant,
} from "@/integrations/google_ads/presenters/write-presenter"
import { titleCaseToken } from "@/lib/format"
import {
  parsePositiveKeywordReference,
  type PositiveKeywordReference,
} from "@/integrations/google_ads/lib/positive-keywords"
import { isNonNegativeInteger, isNullableString, isRecord } from "@/lib/guards"

const OUTCOMES = ["removed", "failed", "unverified"] as const
type RemovalOutcome = (typeof OUTCOMES)[number]

type RemovalArgs = {
  keywords: PositiveKeywordReference[]
}

type RemovalResultRow = {
  errorCode: string | null
  message: string | null
  outcome: RemovalOutcome
  previousStatus: string
  reference: PositiveKeywordReference
  resultingStatus: string | null
}

type RemovalResult = {
  counts: Record<RemovalOutcome, number>
  rows: RemovalResultRow[]
}

const COLUMNS: DataColumn[] = [
  { key: "keyword", kind: "text", label: "Keyword" },
  { key: "scope", kind: "text", label: "Campaign · Ad group" },
  { key: "account", kind: "id", label: "Account" },
  { key: "matchType", kind: "text", label: "Match type" },
  { key: "previousStatus", kind: "status", label: "Before" },
  { key: "requested", kind: "status", label: "Requested" },
  { key: "resultingStatus", kind: "status", label: "After" },
  { key: "outcome", kind: "status", label: "Outcome" },
  { key: "details", kind: "text", label: "Details" },
]

export const googleAdsRemovePositiveKeywordsPresenter = createGoogleAdsWritePresenter({
  key: "google-ads-remove-positive-keywords",
  variants: {
    google_ads_remove_keywords: defineGoogleAdsWriteVariant({
      approval: {
        approveLabel: "Approve & Remove",
        label: "Remove Google Ads Keywords",
        parseArgs: removalArgs,
        prompt:
          "Permanently remove these positive keywords from Google Ads. Removed keywords cannot be re-enabled.",
        renderSummary: (value, fallback) =>
          renderRemovalApprovalSummary(removalArgs(value) ?? fallback),
        title: "Permanently Remove Keywords",
      },
      deniedDescription: "This keyword removal was declined. Nothing was removed.",
      details: (args) => (args ? [{ label: "Keywords", value: String(args.keywords.length) }] : []),
      emptyLabel: "No Google Ads accounts removed keywords.",
      failedDescription: "The removal did not finish. No keyword removal was confirmed.",
      heading: "Remove Keywords",
      malformedDescription:
        "The system couldn't verify this account's keyword removal outcomes. Check Google Ads before taking further action.",
      parseResult: removalResult,
      progressLabel: "Removing Google Ads keywords…",
      renderOutcome: renderRemovalOutcomeTable,
      resultAriaLabel: "Google Ads keyword removal results",
      resultFailure:
        "The system couldn't verify the keyword removals. Check Google Ads before taking further action.",
      unconfirmedAriaLabel: "Unconfirmed Google Ads keyword removal",
      unverifiedDescription:
        "The system couldn't verify whether Google Ads removed these keywords. Check Google Ads before retrying.",
      waitingLabel: "Waiting for keyword removal approval…",
    }),
  },
})

function renderRemovalApprovalSummary(args: RemovalArgs) {
  return (
    <section
      aria-label="Keywords selected for permanent removal"
      className="border-destructive/35 bg-destructive/5 grid gap-2 rounded-lg border px-3 py-2.5"
    >
      <p className="text-destructive text-xs font-medium">
        This action cannot be undone. Removed keywords stop targeting traffic and cannot be
        re-enabled.
      </p>
      <div className="grid gap-1" role="list">
        {args.keywords.map((keyword) => (
          <div
            className="bg-card flex min-w-0 flex-wrap items-baseline justify-between gap-2 rounded-md border px-2.5 py-2"
            key={keyword.identity}
            role="listitem"
          >
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{keyword.label}</p>
              <p className="text-muted-foreground text-xs">
                {keyword.scopeLabel} · Account {keyword.customerId} · {keyword.matchType}
              </p>
            </div>
            <p className="text-sm font-semibold tabular-nums">
              {titleCaseToken(keyword.status, keyword.status)}
            </p>
          </div>
        ))}
      </div>
    </section>
  )
}

function renderRemovalOutcomeTable(result: RemovalResult) {
  const rows = result.rows.map<DataRow>((row) => {
    const details = [row.message]
    if (row.errorCode) {
      details.push(titleCaseToken(row.errorCode, row.errorCode))
    }
    return {
      keyword: row.reference.text,
      scope: row.reference.scopeLabel,
      account: row.reference.customerId,
      matchType: titleCaseToken(row.reference.matchType, row.reference.matchType),
      requested: "Removed",
      details: details.filter((value): value is string => Boolean(value)).join(" · ") || "—",
      outcome: titleCaseToken(row.outcome, row.outcome),
      previousStatus: titleCaseToken(row.previousStatus, row.previousStatus),
      resultingStatus:
        row.resultingStatus === null
          ? "Unverified"
          : titleCaseToken(row.resultingStatus, row.resultingStatus),
    }
  })
  return (
    <DataTable
      columns={COLUMNS}
      exportFilename="removed-positive-keywords.csv"
      header={
        <StatGroup className="px-3 pt-2">
          <Stat
            label="Removed"
            tone={result.counts.removed > 0 ? "success" : undefined}
            value={result.counts.removed}
          />
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
    />
  )
}

function removalArgs(value: unknown): RemovalArgs | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["keywords"]) ||
    value["keywords"].length === 0 ||
    value["keywords"].length > 500
  ) {
    return null
  }
  const keywords: PositiveKeywordReference[] = []
  const keywordIds = new Set<string>()
  for (const valueKeyword of value["keywords"]) {
    const keyword = parsePositiveKeywordReference(valueKeyword)
    const identity = keyword ? keyword.identity : null
    if (!keyword || identity === null || keywordIds.has(identity)) {
      return null
    }
    keywordIds.add(identity)
    keywords.push(keyword)
  }
  return { keywords }
}

function removalResult(value: unknown): RemovalResult | null {
  if (
    !isRecord(value) ||
    !isRecord(value["counts"]) ||
    !isRecord(value["samples"]) ||
    value["samples_truncated"] !== false
  ) {
    return null
  }
  const counts = value["counts"]
  if (
    !isNonNegativeInteger(counts["removed"]) ||
    !isNonNegativeInteger(counts["failed"]) ||
    !isNonNegativeInteger(counts["unverified"])
  ) {
    return null
  }
  const rows: RemovalResultRow[] = []
  const identities = new Set<string>()
  for (const outcome of OUTCOMES) {
    const samples = value["samples"][outcome]
    if (!Array.isArray(samples) || samples.length !== counts[outcome]) {
      return null
    }
    for (const sample of samples) {
      if (
        !isRecord(sample) ||
        sample["outcome"] !== outcome ||
        typeof sample["previous_status"] !== "string" ||
        !isNullableString(sample["resulting_status"] ?? null) ||
        !isNullableString(sample["error_code"] ?? null) ||
        !isNullableString(sample["message"] ?? null)
      ) {
        return null
      }
      const reference = parsePositiveKeywordReference(sample["reference"])
      if (
        !reference ||
        identities.has(reference.identity) ||
        sample["previous_status"] !== reference.status ||
        sample["resulting_status"] !==
          (outcome === "removed" ? "REMOVED" : outcome === "failed" ? reference.status : null)
      ) {
        return null
      }
      identities.add(reference.identity)
      rows.push({
        errorCode: typeof sample["error_code"] === "string" ? sample["error_code"] : null,
        message: typeof sample["message"] === "string" ? sample["message"] : null,
        outcome,
        previousStatus: sample["previous_status"],
        reference,
        resultingStatus:
          typeof sample["resulting_status"] === "string" ? sample["resulting_status"] : null,
      })
    }
  }
  const parsedCounts = {
    failed: counts["failed"],
    removed: counts["removed"],
    unverified: counts["unverified"],
  }
  if (rows.length !== parsedCounts.removed + parsedCounts.failed + parsedCounts.unverified) {
    return null
  }
  if (rows.length > 500) return null
  return { counts: parsedCounts, rows }
}
