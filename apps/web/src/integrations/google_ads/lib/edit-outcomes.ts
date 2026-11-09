// apps/web/src/integrations/google_ads/lib/edit-outcomes.ts

import type { DataTableTab } from "@/components/ui/data-table"

/** What the edit seam reports for each change. */
export type EditOutcome = "updated" | "already_set" | "failed" | "unverified"

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
