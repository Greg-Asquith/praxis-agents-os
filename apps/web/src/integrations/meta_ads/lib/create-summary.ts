// apps/web/src/integrations/meta_ads/lib/create-summary.ts

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-card"
import type { EditedValue } from "@/components/tool-ui/edited-values"
import { isNonEmptyString, isOneOf, isRecord, stringValue } from "@/lib/guards"

const DAY = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
})

type CreateOutcome = "created" | "failed" | "unverified"
const OUTCOMES: ReadonlySet<CreateOutcome> = new Set(["created", "failed", "unverified"])

export type CreatedObjectResult = {
  accountId: string
  name: string
  outcome: CreateOutcome
  recovered: boolean
  id: string | null
  effectiveStatus: string | null
  message: string | null
  errorCode: string | null
}

function day(value: string): string {
  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isNaN(parsed.getTime()) ? value : DAY.format(parsed)
}

export function scheduleSummary(startDate: string | null, endDate: string | null): string {
  const start = startDate ? `From ${day(startDate)}` : "Starts when turned on"
  return `${start} · ${endDate ? `until ${day(endDate)}` : "no end date"}`
}

/** Applies several edits in one decision change; separate edits in one handler would overwrite each other. */
export function editFields(
  controls: ToolApprovalDecisionControls,
  disabled: boolean,
  edits: Record<string, EditedValue>
): void {
  if (disabled) return
  controls.onDecisionChange({
    decision: "pending",
    edits: { ...controls.decision.edits, ...edits },
    message: "",
  })
}

/** Reads the one campaign or ad set a create call made, held under `key` with its ID in `idKey`. */
export function parseCreatedObject(
  value: unknown,
  key: "campaign" | "ad_set",
  idKey: "campaign_id" | "adset_id"
): CreatedObjectResult | null {
  if (!isRecord(value) || !isNonEmptyString(value["account_id"])) return null
  const created = value[key]
  if (!isRecord(created) || !isNonEmptyString(created["name"])) return null
  if (!isOneOf(OUTCOMES, created["outcome"])) return null
  return {
    accountId: value["account_id"],
    name: created["name"],
    outcome: created["outcome"],
    recovered: created["recovered"] === true,
    id: stringValue(created[idKey]),
    effectiveStatus: stringValue(created["effective_status"]),
    message: stringValue(created["message"]),
    errorCode: stringValue(created["error_code"]),
  }
}
