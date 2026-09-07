// apps/web/src/integrations/google_ads/presenters/remove-positive-keywords.tsx

import type { GoogleAdsOutcomeColumn as DataColumn } from "@/integrations/google_ads/components/outcome-table"

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import {
  OUTCOMES,
  type RemovalArgs,
  type RemovalResult,
  type RemovalResultRow,
  renderRemovalApprovalSummary,
  renderRemovalOutcomeTable,
} from "@/integrations/google_ads/components/remove-positive-keywords"
import { googleAdsWriteCopy } from "@/integrations/google_ads/lib/copy"
import {
  parsePositiveKeywordReference,
  type PositiveKeywordReference,
} from "@/integrations/google_ads/lib/positive-keywords"
import {
  createGoogleAdsWritePresenter,
  defineGoogleAdsWriteVariant,
} from "@/integrations/google_ads/presenters/write-presenter"
import { isNonNegativeInteger, isNullableString, isRecord } from "@/lib/guards"

const COLUMNS: DataColumn[] = [
  { key: "keyword", kind: "text", label: "Keyword" },
  { key: "scope", kind: "text", label: "Campaign · Ad group" },
  { key: "account", kind: "id", label: "Account" },
  { key: "matchType", kind: "text", label: "Match type" },
  { key: "previousStatus", kind: "status", label: "Before" },
  { key: "requested", kind: "status", label: "Requested" },
  { key: "resultingStatus", kind: "status", label: "After" },
]

const copy = googleAdsWriteCopy({ verb: "Remove", object: "keywords", effect: "removed" })

export const googleAdsRemovePositiveKeywordsPresenter = createGoogleAdsWritePresenter({
  key: "google-ads-remove-positive-keywords",
  variants: {
    google_ads_remove_keywords: defineGoogleAdsWriteVariant({
      ...copy,
      approval: {
        ...copy.approval,
        parseArgs: removalArgs,
        prompt:
          "Permanently remove these positive keywords from Google Ads. Removed keywords cannot be re-enabled.",
        renderSummary: (value, fallback) =>
          renderRemovalApprovalSummary(removalArgs(value) ?? fallback),
      },
      details: (args) => (args ? [{ label: "Keywords", value: String(args.keywords.length) }] : []),
      parseResult: removalResult,
      renderFailure: (args, description) => (
        <GoogleAdsFailureTargets
          description={description}
          targets={args?.keywords.map((item) => item.label) ?? []}
        />
      ),
      renderOutcome: (result) => renderRemovalOutcomeTable(result, COLUMNS),
    }),
  },
})

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
