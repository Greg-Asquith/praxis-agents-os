// apps/web/src/integrations/meta_ads/lib/create-summary.ts

import { isNonEmptyString, isOneOf, isRecord, stringValue } from "@/lib/guards"

const DAY = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
})
export const PAUSED_NOTE = "This is created paused. Nothing runs or spends until you turn it on."

type CreateOutcome = "created" | "failed" | "unverified"
const OUTCOMES: ReadonlySet<CreateOutcome> = new Set(["created", "failed", "unverified"])

export type SummaryLine = { label: string; sentences: string[] }

export type CreatedObjectResult = {
  accountId: string
  name: string
  outcome: CreateOutcome
  recovered: boolean
  id: string | null
  message: string | null
  errorCode: string | null
}

function day(value: string): string {
  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isNaN(parsed.getTime()) ? value : DAY.format(parsed)
}

export function scheduleSentence(
  startDate: string | null,
  endDate: string | null,
  timezone: string | null
): string {
  const start = startDate ? `Starts ${day(startDate)}` : "Starts when you turn it on"
  const end = endDate ? `ends ${day(endDate)}` : "runs until you turn it off"
  return `${start} and ${end}${timezone ? ` (${timezone})` : ""}.`
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
    message: stringValue(created["message"]),
    errorCode: stringValue(created["error_code"]),
  }
}
