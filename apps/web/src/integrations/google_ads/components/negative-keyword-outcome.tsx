// apps/web/src/integrations/google_ads/components/negative-keyword-outcome.tsx

import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import {
  GoogleAdsEntityCard,
  GoogleAdsEntityGroup,
} from "@/integrations/google_ads/components/entity-card"
import { GoogleAdsApprovalSection } from "@/integrations/google_ads/components/approval-section"
import type { DataColumn, DataRow } from "@/components/ui/data-table"
import {
  GoogleAdsOutcomeTable,
  type GoogleAdsOutcomeRow,
} from "@/integrations/google_ads/components/outcome-table"
import { outcomeLabel } from "@/integrations/google_ads/lib/outcomes"

export type NegativeKeyword = {
  matchType: MatchType
  text: string
}

type NegativeKeywordErrorBase = {
  errorCode: string
  message: string
}

export type NegativeKeywordError =
  | (NegativeKeywordErrorBase & NegativeKeyword & { scope: "keyword" })
  | (NegativeKeywordErrorBase & { scope: "account" })

export type NegativeKeywordResult = {
  addedCount: number
  addedKeywords: NegativeKeyword[]
  errors: NegativeKeywordError[]
  failedCount: number
  samplesTruncated: boolean
  skippedCount: number
  skippedExisting: NegativeKeyword[]
}

export type NegativeKeywordRemovalResult = {
  errors: NegativeKeywordError[]
  failedCount: number
  notFound: NegativeKeyword[]
  notFoundCount: number
  removedCount: number
  removedKeywords: NegativeKeyword[]
  samplesTruncated: boolean
}

export type MatchType = "ANY" | "BROAD" | "EXACT" | "PHRASE"

type CampaignNegativeKeywordError = NegativeKeywordErrorBase & NegativeKeyword

type TargetNegativeKeywordOutcome = NegativeKeyword & {
  errorCode?: string
  externalRef?: string
  outcome: "added" | "failed" | "not_found" | "removed" | "skipped_existing"
}

type CampaignNegativeKeywordRow = {
  campaignId: string
  campaignName: string
  counts: {
    applied: number
    failed: number
    skipped: number
  }
  errors: CampaignNegativeKeywordError[]
  errorsTruncated: boolean
  keywordOutcomes: TargetNegativeKeywordOutcome[] | null
}

export type CampaignNegativeKeywordResult = {
  campaigns: CampaignNegativeKeywordRow[]
  campaignsTruncated: boolean
  totals: {
    applied: number
    failed: number
    skipped: number
  }
}

type AdGroupNegativeKeywordRow = {
  adGroupId: string
  adGroupName: string
  campaignName: string
  counts: {
    applied: number
    failed: number
    skipped: number
  }
  errors: CampaignNegativeKeywordError[]
  errorsTruncated: boolean
  keywordOutcomes: TargetNegativeKeywordOutcome[] | null
}

export type AdGroupNegativeKeywordResult = {
  adGroups: AdGroupNegativeKeywordRow[]
  adGroupsTruncated: boolean
  totals: {
    applied: number
    failed: number
    skipped: number
  }
}

const COLUMNS: DataColumn[] = [
  { key: "text", kind: "text", label: "Keyword" },
  { key: "matchType", kind: "badge", label: "Match Type" },
]
const NO_SELECTION_LABELS: string[] = []

export function NegativeKeywordApprovalSummary({
  includeAny = false,
  listName,
  keywords,
  total = keywords.length,
}: {
  includeAny?: boolean
  listName: string
  keywords: NegativeKeyword[]
  total?: number
}) {
  const counts = matchTypeCounts(keywords)
  return (
    <GoogleAdsApprovalSection
      ariaLabel="Proposed list keyword changes"
      countLine={`${approvalCountLine(total, "keyword")} · ${listName}`}
    >
      <p className="text-muted-foreground text-xs">
        Exact {String(counts.EXACT)} · Phrase {String(counts.PHRASE)} · Broad {String(counts.BROAD)}
        {includeAny ? ` · Any ${String(counts.ANY)}` : null}
      </p>
    </GoogleAdsApprovalSection>
  )
}

export function CampaignNegativeKeywordApprovalSummary({
  campaignCount,
  keywordCount,
}: {
  campaignCount: number
  keywordCount: number
}) {
  return (
    <ScopedNegativeKeywordApprovalSummary
      entityCount={campaignCount}
      entityLabel="campaign"
      keywordCount={keywordCount}
    />
  )
}

export function AdGroupNegativeKeywordApprovalSummary({
  adGroupCount,
  keywordCount,
  selectionLabels,
}: {
  adGroupCount: number
  keywordCount: number
  selectionLabels: string[]
}) {
  return (
    <ScopedNegativeKeywordApprovalSummary
      entityCount={adGroupCount}
      entityLabel="ad group"
      keywordCount={keywordCount}
      selectionLabels={selectionLabels}
    />
  )
}

function ScopedNegativeKeywordApprovalSummary({
  entityCount,
  entityLabel,
  keywordCount,
  selectionLabels = NO_SELECTION_LABELS,
}: {
  entityCount: number
  entityLabel: "ad group" | "campaign"
  keywordCount: number
  selectionLabels?: string[]
}) {
  return (
    <GoogleAdsApprovalSection
      ariaLabel={`Proposed ${entityLabel} keyword changes`}
      countLine={`${approvalCountLine(keywordCount, "keyword")} × ${approvalCountLine(entityCount, entityLabel)} · ${approvalCountLine(entityCount * keywordCount, "proposed change")}`}
    >
      {selectionLabels.length > 0 ? (
        <GoogleAdsEntityGroup title="Ad groups">
          {selectionLabels.map((label, index) => (
            <GoogleAdsEntityCard key={`${String(index)}:${label}`} title={label} />
          ))}
        </GoogleAdsEntityGroup>
      ) : null}
    </GoogleAdsApprovalSection>
  )
}

export function CampaignNegativeKeywordOutcome({
  action,
  result,
}: {
  action: "add" | "remove"
  result: CampaignNegativeKeywordResult
}) {
  return (
    <ScopedNegativeKeywordOutcome
      action={action}
      totals={result.totals}
      targets={result.campaigns.map((target) => ({
        ...target,
        identity: {
          campaign: target.campaignName || target.campaignId,
          campaignId: target.campaignId,
        },
      }))}
      columns={[
        { key: "campaign", kind: "text", label: "Campaign" },
        { key: "campaignId", kind: "text", label: "Campaign ID" },
      ]}
      truncated={result.campaignsTruncated}
      exportFilename={`${action === "add" ? "added" : "removed"}-campaign-negative-keywords.csv`}
    />
  )
}

export function AdGroupNegativeKeywordOutcome({
  action,
  result,
}: {
  action: "add" | "remove"
  result: AdGroupNegativeKeywordResult
}) {
  return (
    <ScopedNegativeKeywordOutcome
      action={action}
      totals={result.totals}
      targets={result.adGroups.map((target) => ({
        ...target,
        identity: {
          adGroup: target.adGroupName || target.adGroupId,
          adGroupId: target.adGroupId,
          campaign: target.campaignName,
        },
      }))}
      columns={[
        { key: "adGroup", kind: "text", label: "Ad Group" },
        { key: "adGroupId", kind: "text", label: "Ad Group ID" },
        { key: "campaign", kind: "text", label: "Campaign" },
      ]}
      truncated={result.adGroupsTruncated}
      exportFilename={`${action === "add" ? "added" : "removed"}-ad-group-negative-keywords.csv`}
    />
  )
}

function ScopedNegativeKeywordOutcome({
  action,
  targets,
  totals,
  columns,
  truncated,
  exportFilename,
}: {
  action: "add" | "remove"
  targets: (Pick<
    CampaignNegativeKeywordRow,
    "counts" | "errors" | "errorsTruncated" | "keywordOutcomes"
  > & { identity: DataRow })[]
  totals: CampaignNegativeKeywordResult["totals"]
  columns: DataColumn[]
  truncated: boolean
  exportFilename: string
}) {
  const applied = action === "add" ? "added" : "removed"
  const skipped = action === "add" ? "skipped_existing" : "not_found"
  const hasExactEvidence = targets.every((target) => target.keywordOutcomes !== null)
  const rows = targets.flatMap<GoogleAdsOutcomeRow>((target) =>
    hasExactEvidence
      ? (target.keywordOutcomes ?? []).map((outcome) => ({
          ...target.identity,
          keyword: outcome.text,
          matchType: outcome.matchType,
          outcome: outcome.outcome,
          details: outcomeDetail(outcome, target.errors),
          errorCode: outcome.errorCode ?? "",
          externalRef: outcome.externalRef ?? "",
        }))
      : (
          [
            [applied, target.counts.applied],
            [skipped, target.counts.skipped],
            ["failed", target.counts.failed],
          ] as const
        )
          .filter(([, count]) => count > 0)
          .map(([outcome, count]) => ({
            ...target.identity,
            outcome,
            applied: outcome === applied ? count : 0,
            skipped: outcome === skipped ? count : 0,
            failed: outcome === "failed" ? count : 0,
            details:
              outcome === "failed" ? target.errors.map((error) => error.message).join(" · ") : "",
            errorCode:
              outcome === "failed"
                ? [...new Set(target.errors.map((error) => error.errorCode))]
                : "",
          }))
  )
  const leadingColumns: DataColumn[] = [
    ...columns,
    ...(hasExactEvidence
      ? ([
          { key: "keyword", kind: "text", label: "Keyword" },
          { key: "matchType", kind: "badge", label: "Match Type" },
          ...(rows.some((row) => row["externalRef"])
            ? [
                {
                  key: "externalRef",
                  kind: "text",
                  label: "External Reference",
                } satisfies DataColumn,
              ]
            : []),
        ] satisfies DataColumn[])
      : ([
          { key: "applied", kind: "text", label: outcomeLabel(applied) },
          { key: "skipped", kind: "text", label: outcomeLabel(skipped) },
          { key: "failed", kind: "text", label: "Failed" },
        ] satisfies DataColumn[])),
  ]
  return (
    <GoogleAdsOutcomeTable
      columns={leadingColumns}
      rows={rows}
      exportFilename={exportFilename}
      outcomes={[
        { kind: "applied", label: outcomeLabel(applied), count: totals.applied },
        { kind: "skipped", label: outcomeLabel(skipped), count: totals.skipped },
        { kind: "failed", label: outcomeLabel("failed"), count: totals.failed },
      ]}
      truncated={truncated || targets.some((target) => target.errorsTruncated)}
    />
  )
}

export function NegativeKeywordRemovalOutcome({
  result,
}: {
  result: NegativeKeywordRemovalResult
}) {
  const rows: GoogleAdsOutcomeRow[] = [
    ...result.removedKeywords.map((keyword) => ({ ...keyword, outcome: "removed" as const })),
    ...result.notFound.map((keyword) => ({ ...keyword, outcome: "not_found" as const })),
    ...errorRows(result.errors),
  ]
  return (
    <GoogleAdsOutcomeTable
      columns={COLUMNS}
      rows={rows}
      exportFilename="removed-negative-keywords.csv"
      outcomes={[
        { kind: "applied", label: outcomeLabel("removed"), count: result.removedCount },
        { kind: "skipped", label: outcomeLabel("not_found"), count: result.notFoundCount },
        { kind: "failed", label: outcomeLabel("failed"), count: result.failedCount },
      ]}
      truncated={result.samplesTruncated}
    />
  )
}

export function NegativeKeywordOutcome({ result }: { result: NegativeKeywordResult }) {
  const rows: GoogleAdsOutcomeRow[] = [
    ...result.addedKeywords.map((keyword) => ({ ...keyword, outcome: "added" as const })),
    ...result.skippedExisting.map((keyword) => ({
      ...keyword,
      outcome: "skipped_existing" as const,
    })),
    ...errorRows(result.errors),
  ]
  return (
    <GoogleAdsOutcomeTable
      columns={COLUMNS}
      rows={rows}
      exportFilename="negative-keywords.csv"
      outcomes={[
        { kind: "applied", label: outcomeLabel("added"), count: result.addedCount },
        { kind: "skipped", label: outcomeLabel("skipped_existing"), count: result.skippedCount },
        { kind: "failed", label: outcomeLabel("failed"), count: result.failedCount },
      ]}
      truncated={result.samplesTruncated}
    />
  )
}

function errorRows(errors: NegativeKeywordError[]): GoogleAdsOutcomeRow[] {
  return errors.map((error) => ({
    errorCode: error.errorCode,
    matchType: error.scope === "keyword" ? error.matchType : "—",
    details: error.message,
    outcome: "failed",
    text: error.scope === "keyword" ? error.text : "Account-level error",
  }))
}

function matchTypeCounts(keywords: NegativeKeyword[]): Record<MatchType, number> {
  const counts: Record<MatchType, number> = { ANY: 0, BROAD: 0, EXACT: 0, PHRASE: 0 }
  for (const keyword of keywords) {
    counts[keyword.matchType] += 1
  }
  return counts
}

function outcomeDetail(
  outcome: TargetNegativeKeywordOutcome,
  errors: CampaignNegativeKeywordError[]
): string {
  if (outcome.outcome !== "failed") return ""
  return (
    errors.find((error) => error.text === outcome.text && error.matchType === outcome.matchType)
      ?.message ?? ""
  )
}
