// apps/web/src/integrations/google_ads/components/remove-positive-keywords.tsx

import type { DataColumn } from "@/components/ui/data-table"
import { GoogleAdsApprovalSection } from "@/integrations/google_ads/components/approval-section"
import { GoogleAdsEntityCard } from "@/integrations/google_ads/components/entity-card"
import {
  GoogleAdsOutcomeTable,
  type GoogleAdsOutcomeRow,
} from "@/integrations/google_ads/components/outcome-table"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import { outcomeKind, outcomeLabel } from "@/integrations/google_ads/lib/outcomes"
import type { PositiveKeywordReference } from "@/integrations/google_ads/lib/positive-keywords"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"

export const OUTCOMES = ["removed", "failed", "unverified"] as const

type RemovalOutcome = (typeof OUTCOMES)[number]

export type RemovalArgs = {
  keywords: PositiveKeywordReference[]
}

export type RemovalResultRow = {
  errorCode: string | null
  message: string | null
  outcome: RemovalOutcome
  previousStatus: string
  reference: PositiveKeywordReference
  resultingStatus: string | null
}

export type RemovalResult = {
  counts: Record<RemovalOutcome, number>
  rows: RemovalResultRow[]
}

export function renderRemovalApprovalSummary(args: RemovalArgs) {
  return (
    <GoogleAdsApprovalSection
      ariaLabel="Keywords selected for permanent removal"
      countLine={approvalCountLine(args.keywords.length, "keyword")}
    >
      <p className="text-muted-foreground text-xs">
        This action cannot be undone. Removed keywords stop targeting traffic and cannot be
        re-enabled.
      </p>
      {args.keywords.map((keyword) => (
        <GoogleAdsEntityCard
          key={keyword.identity}
          title={keyword.label}
          meta={
            <>
              {keyword.scopeLabel} · Account {keyword.customerId} ·{" "}
              {googleAdsTokenLabel(keyword.matchType)}
            </>
          }
          trailing={googleAdsTokenLabel(keyword.status, keyword.status)}
        />
      ))}
    </GoogleAdsApprovalSection>
  )
}

export function renderRemovalOutcomeTable(result: RemovalResult, columns: DataColumn[]) {
  const rows = result.rows.map<GoogleAdsOutcomeRow>((row) => ({
    keyword: row.reference.text,
    scope: row.reference.scopeLabel,
    account: row.reference.customerId,
    matchType: googleAdsTokenLabel(row.reference.matchType, row.reference.matchType),
    requested: "Removed",
    details: row.message ?? "",
    outcome: row.outcome,
    errorCode: row.errorCode,
    previousStatus: googleAdsTokenLabel(row.previousStatus, row.previousStatus),
    resultingStatus:
      row.resultingStatus === null
        ? "Unverified"
        : googleAdsTokenLabel(row.resultingStatus, row.resultingStatus),
  }))
  return (
    <GoogleAdsOutcomeTable
      columns={columns}
      exportFilename="removed-positive-keywords.csv"
      outcomes={OUTCOMES.map((outcome) => ({
        kind: outcomeKind(outcome),
        label: outcomeLabel(outcome),
        count: result.counts[outcome],
      }))}
      rows={rows}
    />
  )
}
