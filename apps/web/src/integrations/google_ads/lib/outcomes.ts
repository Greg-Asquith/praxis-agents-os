// apps/web/src/integrations/google_ads/lib/outcomes.ts

import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"

export type OutcomeKind = "applied" | "skipped" | "failed" | "unverified"

const OUTCOMES = {
  updated: ["applied", "Updated"],
  created: ["applied", "Created"],
  assigned: ["applied", "Assigned"],
  removed: ["applied", "Removed"],
  deleted: ["applied", "Deleted"],
  linked: ["applied", "Linked"],
  unlinked: ["applied", "Unlinked"],
  applied: ["applied", "Applied"],
  dismissed: ["applied", "Dismissed"],
  added: ["applied", "Added"],
  already_set: ["skipped", "Already set"],
  already_exists: ["skipped", "Already existed"],
  already_linked: ["skipped", "Already linked"],
  already_applied: ["skipped", "Already applied"],
  not_applied: ["skipped", "Not applied"],
  not_linked: ["skipped", "Not linked"],
  already_dismissed: ["skipped", "Already dismissed"],
  skipped_existing: ["skipped", "Already existed"],
  not_found: ["skipped", "Not found"],
  failed: ["failed", "Failed"],
  unverified: ["unverified", "Unverified"],
} as const satisfies Record<string, readonly [OutcomeKind, string]>

type OutcomeToken = keyof typeof OUTCOMES

export function outcomeKind(token: OutcomeToken): OutcomeKind {
  return OUTCOMES[token][0]
}

export function outcomeLabel(token: OutcomeToken): string {
  return OUTCOMES[token][1]
}

export function outcomeTone(kind: OutcomeKind): "success" | "danger" | "warning" | undefined {
  return (
    { applied: "success", skipped: undefined, failed: "danger", unverified: "warning" } as const
  )[kind]
}

export function outcomeDetails(
  message: string | null,
  errorCode: string | null,
  note: string | null
): string {
  return [message, errorCode ? googleAdsTokenLabel(errorCode) : null, note]
    .filter(Boolean)
    .join(" · ")
}

export function countByKind(rows: readonly { outcome: OutcomeToken }[]) {
  const counts: Record<OutcomeKind, number> = { applied: 0, skipped: 0, failed: 0, unverified: 0 }
  for (const row of rows) counts[outcomeKind(row.outcome)] += 1
  return (["applied", "skipped", "failed", "unverified"] as const).map((kind) => ({
    kind,
    label: googleAdsTokenLabel(kind),
    count: counts[kind],
  }))
}

// True when some items failed and others did not.
export function rowsPartlyFailed(rows: readonly { outcome: string }[]): boolean {
  return partlyFailed(rows.filter((row) => row.outcome === "failed").length, rows.length)
}

export function countsPartlyFailed(counts: Readonly<Record<string, number>>): boolean {
  const total = Object.values(counts).reduce((sum, count) => sum + count, 0)
  return partlyFailed(counts["failed"] ?? 0, total)
}

function partlyFailed(failed: number, total: number): boolean {
  return failed > 0 && failed < total
}
