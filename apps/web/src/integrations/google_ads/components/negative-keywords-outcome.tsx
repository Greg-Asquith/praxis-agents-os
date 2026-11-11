// apps/web/src/integrations/google_ads/components/negative-keywords-outcome.tsx

import { useMemo, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import { cellText } from "@/integrations/ads/lib/cell-text"
import {
  MATCH_TYPE_LABELS,
  TARGET_KIND_LABELS,
} from "@/integrations/google_ads/lib/negative-keywords"
import {
  NEGATIVE_OUTCOME_BADGES,
  NEGATIVE_OUTCOME_LABELS,
  NEGATIVE_OUTCOME_TABS,
  negativeOutcomeSummary,
  type NegativeOutcome,
  type UpdateNegativeKeywordsResult,
} from "@/integrations/google_ads/lib/negative-keywords-result"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"

const COLUMNS: DataColumn[] = [
  { key: "name", kind: "text", label: "Negative Keyword", width: 240 },
  { key: "match", kind: "text", label: "Match Type", width: 110 },
  { key: "target", kind: "text", label: "Target", width: 220 },
  { key: "outcome", kind: "text", label: "Outcome", width: 140 },
  { key: "details", kind: "text", label: "Details", hidden: true },
]

type Row = UpdateNegativeKeywordsResult["rows"][number]

const SECTIONS = [
  { action: "add", title: "Added Negative Keywords", target: "Added To" },
  { action: "remove", title: "Removed Negative Keywords", target: "Removed From" },
] as const

/** Adds and removes as two tables, like the approval; each opens on its failures. */
export function NegativeKeywordsOutcome({ result }: { result: UpdateNegativeKeywordsResult }) {
  return (
    <div className="grid min-w-0 gap-4">
      {SECTIONS.map((section) => {
        // Starting a new list is part of adding its keywords.
        const rows = result.rows.filter((row) =>
          section.action === "add" ? row.action !== "remove" : row.action === "remove"
        )
        return rows.length > 0 ? (
          <section key={section.action} aria-label={section.title} className="grid gap-2">
            <h3 className="text-sm font-medium">
              {section.title}{" "}
              <span className="text-muted-foreground tabular-nums">
                {rows.length.toLocaleString("en-GB")}
              </span>
            </h3>
            <OutcomeTable rows={rows} targetLabel={section.target} />
          </section>
        ) : null
      })}
    </div>
  )
}

function OutcomeTable({ rows, targetLabel }: { rows: readonly Row[]; targetLabel: string }) {
  const [tab, setTab] = useState(rows.some((row) => row.outcome === "failed") ? "failed" : "all")
  const tableRows = useMemo(
    () =>
      rows.map((row) => ({
        details: [row.message, row.errorCode ? googleAdsTokenLabel(row.errorCode) : null]
          .filter(Boolean)
          .join(" · "),
        match: row.matchType ? MATCH_TYPE_LABELS[row.matchType] : "",
        name:
          row.item === "campaign"
            ? `${row.action === "add" ? "Uses list" : "Stops using list"}: ${row.name}`
            : row.item === "list"
              ? `New list: ${row.name}`
              : row.name,
        outcome: NEGATIVE_OUTCOME_LABELS[row.outcome],
        target: `${row.targetName} · ${TARGET_KIND_LABELS[row.targetKind]}`,
        token: row.outcome,
      })),
    [rows]
  )
  const columns = useMemo(
    () =>
      COLUMNS.map((column) =>
        column.key === "target" ? { ...column, label: targetLabel } : column
      ),
    [targetLabel]
  )
  return (
    <DataTable
      activeTab={tab}
      columns={columns}
      exportFilename="google-ads-negative-keywords.csv"
      onTabChange={setTab}
      pageSize={10}
      renderCell={(column, row) => {
        if (column.key === "outcome")
          return (
            <Badge variant={NEGATIVE_OUTCOME_BADGES[row["token"] as NegativeOutcome]}>
              {cellText(row["outcome"])}
            </Badge>
          )
        if (column.key === "name")
          return (
            <span className="grid gap-0.5 whitespace-normal">
              <span className="wrap-anywhere">{cellText(row["name"])}</span>
              {row["token"] === "failed" && row["details"] ? (
                <span className="text-destructive text-xs wrap-anywhere">
                  {cellText(row["details"])}
                </span>
              ) : null}
            </span>
          )
        return null
      }}
      rowNoun={["change", "changes"]}
      rows={tableRows}
      summary={<span>{negativeOutcomeSummary(rows)}</span>}
      tabs={NEGATIVE_OUTCOME_TABS}
    />
  )
}
