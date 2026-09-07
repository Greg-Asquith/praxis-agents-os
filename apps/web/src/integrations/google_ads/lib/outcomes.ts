// apps/web/src/integrations/google_ads/lib/outcomes.ts

import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"

export type OutcomeKind = "applied" | "skipped" | "failed" | "unverified"

const OUTCOMES = {
  updated: ["applied", "Updated"],
  created: ["applied", "Created"],
  assigned: ["applied", "Assigned"],
  removed: ["applied", "Removed"],
  linked: ["applied", "Linked"],
  unlinked: ["applied", "Unlinked"],
  applied: ["applied", "Applied"],
  dismissed: ["applied", "Dismissed"],
  added: ["applied", "Added"],
  already_set: ["skipped", "Already set"],
  already_exists: ["skipped", "Already existed"],
  already_linked: ["skipped", "Already linked"],
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
