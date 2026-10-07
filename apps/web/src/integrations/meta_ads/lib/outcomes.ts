// apps/web/src/integrations/meta_ads/lib/outcomes.ts

import { titleCaseToken } from "@/lib/format"

export type OutcomeKind = "applied" | "skipped" | "failed" | "unverified"

const OUTCOMES = {
  updated: ["applied", "Updated"],
  created: ["applied", "Created"],
  uploaded: ["applied", "Uploaded"],
  processing: ["applied", "Processing"],
  already_set: ["skipped", "Already Set"],
  failed: ["failed", "Failed"],
  unverified: ["unverified", "Couldn't Confirm"],
} as const satisfies Record<string, readonly [OutcomeKind, string]>

export type OutcomeToken = keyof typeof OUTCOMES

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

export function countByKind(rows: readonly { outcome: OutcomeToken }[]) {
  const counts: Record<OutcomeKind, number> = { applied: 0, skipped: 0, failed: 0, unverified: 0 }
  for (const row of rows) counts[outcomeKind(row.outcome)] += 1
  return (["applied", "skipped", "failed", "unverified"] as const).map((kind) => ({
    kind,
    label: titleCaseToken(kind, kind),
    count: counts[kind],
  }))
}
