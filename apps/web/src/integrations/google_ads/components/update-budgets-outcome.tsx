// apps/web/src/integrations/google_ads/components/update-budgets-outcome.tsx

import { useMemo, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import {
  EDIT_OUTCOME_BADGES,
  EDIT_OUTCOME_LABELS,
  EDIT_OUTCOME_TABS,
  editOutcomeSummary,
  type EditOutcome,
} from "@/integrations/google_ads/lib/edit-outcomes"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"
import {
  BUDGET_SETTING_TITLES,
  budgetValueText,
} from "@/integrations/google_ads/lib/update-budgets"
import type {
  BudgetOutcomeRow,
  UpdateBudgetsResult,
} from "@/integrations/google_ads/lib/update-budgets-result"

const COLUMNS: DataColumn[] = [
  { key: "name", kind: "text", label: "Campaign or Budget", width: 220 },
  { key: "setting", kind: "text", label: "Setting", width: 130 },
  { key: "before", kind: "text", label: "Before", width: 150 },
  { key: "after", kind: "text", label: "After", width: 150 },
  { key: "outcome", kind: "text", label: "Outcome", width: 110 },
  { key: "details", kind: "text", label: "Details", hidden: true },
]

function afterText(row: BudgetOutcomeRow, currency: string | null): string {
  return row.outcome === "failed" || !row.readBack
    ? "—"
    : budgetValueText(row.setting, row.after, currency)
}

/** One row per changed setting, opening on the failures when there are any. */
export function UpdateBudgetsOutcome({ result }: { result: UpdateBudgetsResult }) {
  const [tab, setTab] = useState(
    result.rows.some((row) => row.outcome === "failed") ? "failed" : "all"
  )
  const rows = useMemo(
    () =>
      result.rows.map((row) => ({
        after: afterText(row, result.currency),
        before: budgetValueText(row.setting, row.before, result.currency),
        details: [row.message, row.errorCode ? googleAdsTokenLabel(row.errorCode) : null]
          .filter(Boolean)
          .join(" · "),
        name: row.name,
        outcome: EDIT_OUTCOME_LABELS[row.outcome],
        setting: BUDGET_SETTING_TITLES[row.setting],
        token: row.outcome,
      })),
    [result]
  )
  return (
    <DataTable
      activeTab={tab}
      columns={COLUMNS}
      exportFilename="google-ads-budget-changes.csv"
      onTabChange={setTab}
      pageSize={25}
      renderCell={(column, row) => {
        if (column.key === "outcome")
          return (
            <Badge variant={EDIT_OUTCOME_BADGES[row["token"] as EditOutcome]}>
              {cellText(row["outcome"])}
            </Badge>
          )
        if (column.key === "name" && row["token"] === "failed" && cellText(row["details"]))
          return (
            <span className="grid gap-0.5">
              <span className="wrap-anywhere whitespace-normal">{cellText(row["name"])}</span>
              <span className="text-destructive text-xs wrap-anywhere whitespace-normal">
                {cellText(row["details"])}
              </span>
            </span>
          )
        if (column.key === "name" || column.key === "before" || column.key === "after")
          return (
            <span className="wrap-anywhere whitespace-normal">{cellText(row[column.key])}</span>
          )
        return null
      }}
      rowNoun={["change", "changes"]}
      rows={rows}
      summary={<span>{editOutcomeSummary(result.rows)}</span>}
      tabs={EDIT_OUTCOME_TABS}
    />
  )
}

function cellText(value: unknown): string {
  return typeof value === "string" ? value : ""
}
