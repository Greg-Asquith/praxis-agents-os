// apps/web/src/integrations/google_ads/lib/edit-outcomes.ts

import type { DataTableTab } from "@/components/ui/data-table"

/** What the edit seam reports for each change. */
export type EditOutcome = "updated" | "already_set" | "failed" | "unverified"

const EDIT_OUTCOMES: readonly unknown[] = ["updated", "already_set", "failed", "unverified"]

export function isEditOutcome(value: unknown): value is EditOutcome {
  return EDIT_OUTCOMES.includes(value)
}

export const EDIT_OUTCOME_LABELS: Record<EditOutcome, string> = {
  already_set: "Already Set",
  failed: "Failed",
  unverified: "Unconfirmed",
  updated: "Changed",
}

export const EDIT_OUTCOME_BADGES = {
  already_set: "secondary",
  failed: "destructive",
  unverified: "warning",
  updated: "success",
} as const

function outcomeTab(id: EditOutcome | "all", hideWhenEmpty = false): DataTableTab {
  return {
    hideWhenEmpty,
    id,
    label: id === "all" ? "All" : EDIT_OUTCOME_LABELS[id],
    match: (row) => id === "all" || row["token"] === id,
  }
}

// Result tables put each row's outcome in `token`.
export const EDIT_OUTCOME_TABS: DataTableTab[] = [
  outcomeTab("all"),
  outcomeTab("updated"),
  outcomeTab("already_set"),
  outcomeTab("failed"),
  outcomeTab("unverified", true),
]

/** Joins counts with their labels, such as "3 changed · 1 failed", leaving out counts of none. */
export function countsText(
  counts: readonly (readonly [total: number, label: string])[],
  separator = " · "
): string {
  return counts
    .filter(([total]) => total !== 0)
    .map(([total, label]) => `${String(total)} ${label}`)
    .join(separator)
}

/** Counts each outcome; `weight` is how many changes a row stands for, when not one. */
export function editOutcomeSummary<R extends { outcome: EditOutcome }>(
  rows: readonly R[],
  { inReview = 0, weight = () => 1 }: { inReview?: number; weight?: (row: R) => number } = {}
): string {
  const count = (outcome: EditOutcome) =>
    rows.filter((row) => row.outcome === outcome).reduce((sum, row) => sum + weight(row), 0)
  return countsText([
    [count("updated"), "changed"],
    [inReview, "in review"],
    [count("already_set"), "already set"],
    [count("failed"), "failed"],
    [count("unverified"), "unconfirmed"],
  ])
}
