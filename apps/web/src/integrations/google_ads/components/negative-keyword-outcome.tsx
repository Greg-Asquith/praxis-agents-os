// apps/web/src/integrations/google_ads/components/negative-keyword-outcome.tsx

import { KpiStrip } from "@/components/tool-ui/kpi"
import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"

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

type MatchType = "BROAD" | "EXACT" | "PHRASE"

const COLUMNS: DataColumn[] = [
  { key: "text", kind: "text", label: "Keyword" },
  { key: "matchType", kind: "badge", label: "Match Type" },
  { key: "outcome", kind: "status", label: "Outcome" },
]

export function NegativeKeywordApprovalSummary({
  listName,
  keywords,
  total = keywords.length,
}: {
  listName: string
  keywords: NegativeKeyword[]
  total?: number
}) {
  const counts = matchTypeCounts(keywords)
  return (
    <div className="bg-muted/20 grid gap-2 rounded-lg border px-3 py-2.5">
      <p className="text-sm font-medium">
        {String(total)} {total === 1 ? "keyword" : "keywords"}
        <span className="text-muted-foreground"> · {listName}</span>
      </p>
      <p className="text-muted-foreground text-xs">
        Exact {String(counts.EXACT)} · Phrase {String(counts.PHRASE)} · Broad {String(counts.BROAD)}
      </p>
    </div>
  )
}

export function NegativeKeywordOutcome({ result }: { result: NegativeKeywordResult }) {
  const rows = outcomeRows(result)
  return (
    <div className="grid min-w-0 gap-3">
      <KpiStrip
        items={[
          { label: "Added", tone: "success", value: result.addedCount },
          {
            label: "Already existed",
            tone: result.skippedCount > 0 ? "warning" : "neutral",
            value: result.skippedCount,
          },
          {
            label: "Failed",
            tone: result.failedCount > 0 ? "danger" : "neutral",
            value: result.failedCount,
          },
        ]}
      />
      <DataTable columns={COLUMNS} exportFilename="negative-keywords.csv" rows={rows} />
      {result.samplesTruncated ? (
        <p className="text-muted-foreground text-xs">
          Showing representative rows. Full applied-change details are available in the audit trail.
        </p>
      ) : null}
      {result.errors.length > 0 ? (
        <div className="grid gap-1">
          {result.errors.map((error, index) => (
            <p className="text-destructive text-xs" key={errorKey(error, index)}>
              {error.scope === "keyword" ? error.text : "Account-level error"}: {error.message}
            </p>
          ))}
        </div>
      ) : null}
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
    ...result.errors.flatMap((error) =>
      error.scope === "keyword"
        ? [{ matchType: error.matchType, outcome: "Failed", text: error.text }]
        : []
    ),
  ]
}

function errorKey(error: NegativeKeywordError, index: number): string {
  return error.scope === "keyword"
    ? `${error.text}:${error.matchType}:${String(index)}`
    : `account:${error.errorCode}:${String(index)}`
}

function matchTypeCounts(keywords: NegativeKeyword[]): Record<MatchType, number> {
  const counts: Record<MatchType, number> = { BROAD: 0, EXACT: 0, PHRASE: 0 }
  for (const keyword of keywords) {
    counts[keyword.matchType] += 1
  }
  return counts
}
