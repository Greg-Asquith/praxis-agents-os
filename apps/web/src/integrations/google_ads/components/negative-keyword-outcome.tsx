// apps/web/src/integrations/google_ads/components/negative-keyword-outcome.tsx

import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { Stat, StatGroup } from "@/components/ui/stat"

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

export type TargetNegativeKeywordOutcome = NegativeKeyword & {
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
  { key: "outcome", kind: "status", label: "Outcome" },
]
const DIAGNOSTIC_COLUMNS: DataColumn[] = [
  ...COLUMNS,
  { key: "message", kind: "text", label: "Details" },
  { key: "errorCode", kind: "badge", label: "Error Code" },
]
const TRUNCATION_NOTE =
  "Showing representative rows. Full applied-change details are available in the audit trail."
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
    <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 px-0.5">
      <p className="text-sm font-medium">
        {String(total)} {total === 1 ? "keyword" : "keywords"}
        <span className="text-muted-foreground"> · {listName}</span>
      </p>
      <p className="text-muted-foreground text-xs">
        Exact {String(counts.EXACT)} · Phrase {String(counts.PHRASE)} · Broad {String(counts.BROAD)}
        {includeAny ? ` · Any ${String(counts.ANY)}` : null}
      </p>
    </div>
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
  const operationCount = entityCount * keywordCount
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 px-0.5">
      <p className="text-sm font-medium">
        {String(keywordCount)} {keywordCount === 1 ? "keyword" : "keywords"}
        <span className="text-muted-foreground">
          {" "}
          × {String(entityCount)} {entityCount === 1 ? entityLabel : `${entityLabel}s`}
        </span>
      </p>
      <p className="text-muted-foreground text-xs">
        {String(operationCount)} proposed {operationCount === 1 ? "change" : "changes"}
      </p>
      {selectionLabels.length > 0 ? (
        <p className="text-muted-foreground w-full truncate text-xs">
          {selectionLabels.join(" · ")}
        </p>
      ) : null}
    </div>
  )
}

export function CampaignNegativeKeywordOutcome({
  action,
  result,
}: {
  action: "add" | "remove"
  result: CampaignNegativeKeywordResult
}) {
  const appliedLabel = action === "add" ? "Added" : "Removed"
  const skippedLabel = action === "add" ? "Already existed" : "Not found"
  const hasExactEvidence = result.campaigns.every((campaign) => campaign.keywordOutcomes !== null)
  const exactOutcomes = result.campaigns.flatMap((campaign) => campaign.keywordOutcomes ?? [])
  const rows: DataRow[] = hasExactEvidence
    ? result.campaigns.flatMap((campaign) =>
        (campaign.keywordOutcomes ?? []).map((outcome) => ({
          campaign: campaign.campaignName || campaign.campaignId,
          campaignId: campaign.campaignId,
          details: outcomeDetail(outcome, campaign.errors),
          errorCode: outcome.errorCode ?? "",
          externalRef: outcome.externalRef ?? "",
          keyword: outcome.text,
          matchType: outcome.matchType,
          outcome: outcomeLabel(outcome.outcome),
        }))
      )
    : result.campaigns.map((campaign) => ({
        applied: campaign.counts.applied,
        campaign: campaign.campaignName || campaign.campaignId,
        campaignId: campaign.campaignId,
        details: campaign.errors.map((error) => error.message).join(" · "),
        failed: campaign.counts.failed,
        skipped: campaign.counts.skipped,
      }))
  const columns: DataColumn[] = hasExactEvidence
    ? exactOutcomeColumns("campaign", {
        includeDiagnostics: result.totals.failed > 0,
        includeExternalReferences: exactOutcomes.some((outcome) => outcome.externalRef),
      })
    : [
        { key: "campaign", kind: "text", label: "Campaign" },
        { key: "campaignId", kind: "text", label: "Campaign ID" },
        { key: "applied", kind: "text", label: appliedLabel },
        { key: "skipped", kind: "text", label: skippedLabel },
        { key: "failed", kind: "text", label: "Failed" },
        ...(result.totals.failed > 0
          ? ([{ key: "details", kind: "text", label: "Details" }] satisfies DataColumn[])
          : []),
      ]
  return (
    <DataTable
      columns={columns}
      exportFilename={`${action === "add" ? "added" : "removed"}-campaign-negative-keywords.csv`}
      header={
        <StatGroup className="px-3 pt-2">
          <Stat
            label={appliedLabel}
            tone={result.totals.applied > 0 ? "success" : undefined}
            value={result.totals.applied}
          />
          <Stat
            label={skippedLabel}
            tone={result.totals.skipped > 0 ? "warning" : undefined}
            value={result.totals.skipped}
          />
          <Stat
            label="Failed"
            tone={result.totals.failed > 0 ? "danger" : undefined}
            value={result.totals.failed}
          />
        </StatGroup>
      }
      pageSize={25}
      rows={rows}
      truncationNote={
        result.campaignsTruncated || result.campaigns.some((campaign) => campaign.errorsTruncated)
          ? TRUNCATION_NOTE
          : null
      }
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
  const appliedLabel = action === "add" ? "Added" : "Removed"
  const skippedLabel = action === "add" ? "Already existed" : "Not found"
  const hasExactEvidence = result.adGroups.every((adGroup) => adGroup.keywordOutcomes !== null)
  const exactOutcomes = result.adGroups.flatMap((adGroup) => adGroup.keywordOutcomes ?? [])
  const rows: DataRow[] = hasExactEvidence
    ? result.adGroups.flatMap((adGroup) =>
        (adGroup.keywordOutcomes ?? []).map((outcome) => ({
          adGroup: adGroup.adGroupName || adGroup.adGroupId,
          adGroupId: adGroup.adGroupId,
          campaign: adGroup.campaignName,
          details: outcomeDetail(outcome, adGroup.errors),
          errorCode: outcome.errorCode ?? "",
          externalRef: outcome.externalRef ?? "",
          keyword: outcome.text,
          matchType: outcome.matchType,
          outcome: outcomeLabel(outcome.outcome),
        }))
      )
    : result.adGroups.map((adGroup) => ({
        adGroup: adGroup.adGroupName || adGroup.adGroupId,
        adGroupId: adGroup.adGroupId,
        applied: adGroup.counts.applied,
        campaign: adGroup.campaignName,
        details: adGroup.errors.map((error) => error.message).join(" · "),
        failed: adGroup.counts.failed,
        skipped: adGroup.counts.skipped,
      }))
  const columns: DataColumn[] = hasExactEvidence
    ? exactOutcomeColumns("ad_group", {
        includeDiagnostics: result.totals.failed > 0,
        includeExternalReferences: exactOutcomes.some((outcome) => outcome.externalRef),
      })
    : [
        { key: "adGroup", kind: "text", label: "Ad Group" },
        { key: "campaign", kind: "text", label: "Campaign" },
        { key: "adGroupId", kind: "text", label: "Ad Group ID" },
        { key: "applied", kind: "text", label: appliedLabel },
        { key: "skipped", kind: "text", label: skippedLabel },
        { key: "failed", kind: "text", label: "Failed" },
        ...(result.totals.failed > 0
          ? ([{ key: "details", kind: "text", label: "Details" }] satisfies DataColumn[])
          : []),
      ]
  return (
    <DataTable
      columns={columns}
      exportFilename={`${action === "add" ? "added" : "removed"}-ad-group-negative-keywords.csv`}
      header={
        <StatGroup className="px-3 pt-2">
          <Stat
            label={appliedLabel}
            tone={result.totals.applied > 0 ? "success" : undefined}
            value={result.totals.applied}
          />
          <Stat
            label={skippedLabel}
            tone={result.totals.skipped > 0 ? "warning" : undefined}
            value={result.totals.skipped}
          />
          <Stat
            label="Failed"
            tone={result.totals.failed > 0 ? "danger" : undefined}
            value={result.totals.failed}
          />
        </StatGroup>
      }
      pageSize={25}
      rows={rows}
      truncationNote={
        result.adGroupsTruncated || result.adGroups.some((adGroup) => adGroup.errorsTruncated)
          ? TRUNCATION_NOTE
          : null
      }
    />
  )
}

export function NegativeKeywordRemovalOutcome({
  result,
}: {
  result: NegativeKeywordRemovalResult
}) {
  const rows: DataRow[] = [
    ...result.removedKeywords.map((keyword) => ({
      matchType: keyword.matchType,
      outcome: "Success",
      text: keyword.text,
    })),
    ...result.notFound.map((keyword) => ({
      matchType: keyword.matchType,
      outcome: "Not found",
      text: keyword.text,
    })),
    ...errorRows(result.errors),
  ]
  return (
    <div className="grid min-w-0 gap-3">
      <DataTable
        columns={result.errors.length > 0 ? DIAGNOSTIC_COLUMNS : COLUMNS}
        exportFilename="removed-negative-keywords.csv"
        header={
          <StatGroup className="px-3 pt-2">
            <Stat
              label="Removed"
              tone={result.removedCount > 0 ? "success" : undefined}
              value={result.removedCount}
            />
            <Stat
              label="Not found"
              tone={result.notFoundCount > 0 ? "warning" : undefined}
              value={result.notFoundCount}
            />
            <Stat
              label="Failed"
              tone={result.failedCount > 0 ? "danger" : undefined}
              value={result.failedCount}
            />
          </StatGroup>
        }
        pageSize={25}
        rows={rows}
        truncationNote={result.samplesTruncated ? TRUNCATION_NOTE : null}
      />
    </div>
  )
}

export function NegativeKeywordOutcome({ result }: { result: NegativeKeywordResult }) {
  const rows = outcomeRows(result)
  return (
    <div className="grid min-w-0 gap-3">
      <DataTable
        columns={result.errors.length > 0 ? DIAGNOSTIC_COLUMNS : COLUMNS}
        exportFilename="negative-keywords.csv"
        header={
          <StatGroup className="px-3 pt-2">
            <Stat
              label="Added"
              tone={result.addedCount > 0 ? "success" : undefined}
              value={result.addedCount}
            />
            <Stat
              label="Already existed"
              tone={result.skippedCount > 0 ? "warning" : undefined}
              value={result.skippedCount}
            />
            <Stat
              label="Failed"
              tone={result.failedCount > 0 ? "danger" : undefined}
              value={result.failedCount}
            />
          </StatGroup>
        }
        pageSize={25}
        rows={rows}
        truncationNote={result.samplesTruncated ? TRUNCATION_NOTE : null}
      />
    </div>
  )
}

function outcomeRows(result: NegativeKeywordResult): DataRow[] {
  return [
    ...result.addedKeywords.map((keyword) => ({
      matchType: keyword.matchType,
      outcome: "Added",
      text: keyword.text,
    })),
    ...result.skippedExisting.map((keyword) => ({
      matchType: keyword.matchType,
      outcome: "Already existed",
      text: keyword.text,
    })),
    ...errorRows(result.errors),
  ]
}

function errorRows(errors: NegativeKeywordError[]): DataRow[] {
  return errors.map((error) => ({
    errorCode: error.errorCode,
    matchType: error.scope === "keyword" ? error.matchType : "—",
    message: error.message,
    outcome: "Failed",
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

function exactOutcomeColumns(
  target: "ad_group" | "campaign",
  options: { includeDiagnostics: boolean; includeExternalReferences: boolean }
): DataColumn[] {
  return [
    ...(target === "ad_group"
      ? ([
          { key: "adGroup", kind: "text", label: "Ad Group" },
          { key: "adGroupId", kind: "text", label: "Ad Group ID" },
          { key: "campaign", kind: "text", label: "Campaign" },
        ] satisfies DataColumn[])
      : ([
          { key: "campaign", kind: "text", label: "Campaign" },
          { key: "campaignId", kind: "text", label: "Campaign ID" },
        ] satisfies DataColumn[])),
    { key: "keyword", kind: "text", label: "Keyword" },
    { key: "matchType", kind: "badge", label: "Match Type" },
    { key: "outcome", kind: "status", label: "Outcome" },
    ...(options.includeDiagnostics
      ? ([
          { key: "details", kind: "text", label: "Details" },
          { key: "errorCode", kind: "text", label: "Error Code" },
        ] satisfies DataColumn[])
      : []),
    ...(options.includeExternalReferences
      ? ([{ key: "externalRef", kind: "text", label: "External Reference" }] satisfies DataColumn[])
      : []),
  ]
}

function outcomeLabel(outcome: TargetNegativeKeywordOutcome["outcome"]): string {
  switch (outcome) {
    case "added":
      return "Added"
    case "removed":
      return "Removed"
    case "skipped_existing":
      return "Already existed"
    case "not_found":
      return "Not found"
    case "failed":
      return "Failed"
  }
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
