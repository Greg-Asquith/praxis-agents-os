// apps/web/src/integrations/google_ads/lib/copy.ts

export function approvalCountLine(count: number, noun: string): string {
  return `${String(count)} ${noun}${count === 1 ? "" : "s"}`
}

export function unavailableProblem(noun: string): string {
  return `Google Ads couldn't check this ${noun}. Ask the agent to prepare the change again.`
}

/** Why a request of changes can't be approved yet, or null; `settled` says every change is live. */
export function changesBlock(
  counts: { apply: number; problems: number; total: number },
  needsCheck: boolean,
  settled: string
): string | null {
  if (counts.total === 0) return "Every change is cancelled. Decline this request, or undo one."
  if (needsCheck) return "Click Check Changes so Google can check your edits, then approve."
  if (counts.problems > 0)
    return `Fix or cancel ${approvalCountLine(counts.problems, "change")} to continue.`
  return counts.apply === 0 ? settled : null
}

export function applyChangesLabel(apply: number): string {
  return apply === 0
    ? "Apply Changes"
    : `Apply ${apply.toLocaleString("en-GB")} ${apply === 1 ? "Change" : "Changes"}`
}
