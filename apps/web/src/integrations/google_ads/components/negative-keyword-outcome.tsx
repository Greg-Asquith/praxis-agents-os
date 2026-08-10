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
    <div className="bg-muted/50 grid gap-2 rounded-lg px-3 py-2.5">
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
