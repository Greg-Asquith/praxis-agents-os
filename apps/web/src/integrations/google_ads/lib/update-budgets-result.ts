// apps/web/src/integrations/google_ads/lib/update-budgets-result.ts

import { isEditOutcome, type EditOutcome } from "@/integrations/google_ads/lib/edit-outcomes"
import type { BudgetSetting } from "@/integrations/google_ads/lib/update-budgets"
import { isNonEmptyString, isRecord, optionalString } from "@/lib/guards"

export type BudgetOutcomeRow = {
  after: string | null
  before: string | null
  errorCode: string | null
  message: string | null
  name: string
  outcome: EditOutcome
  readBack: boolean
  setting: BudgetSetting
}

export type UpdateBudgetsResult = {
  accountId: string
  currency: string | null
  rows: BudgetOutcomeRow[]
}

const SETTINGS: readonly string[] = ["amount", "delivery", "shared_budget"]

function parseBudget(raw: unknown): BudgetOutcomeRow[] | null {
  if (!isRecord(raw) || !isNonEmptyString(raw["name"]) || !Array.isArray(raw["settings"]))
    return null
  const rows: BudgetOutcomeRow[] = []
  for (const item of raw["settings"]) {
    if (!isRecord(item)) return null
    const setting = item["setting"]
    const outcome = item["outcome"]
    if (typeof setting !== "string" || !SETTINGS.includes(setting)) return null
    if (!isEditOutcome(outcome)) return null
    rows.push({
      after: optionalString(item["after"]),
      before: optionalString(item["before"]),
      errorCode: optionalString(raw["error_code"]),
      message: optionalString(raw["message"]),
      name: raw["name"],
      outcome,
      readBack: raw["read_back"] === true,
      setting: setting as BudgetSetting,
    })
  }
  return rows
}

export function parseUpdateBudgetsResult(raw: unknown): UpdateBudgetsResult | null {
  if (!isRecord(raw) || !isNonEmptyString(raw["account_id"]) || !Array.isArray(raw["budgets"]))
    return null
  const budgets = raw["budgets"].map(parseBudget)
  if (budgets.some((rows) => rows === null)) return null
  return {
    accountId: raw["account_id"],
    currency: isNonEmptyString(raw["currency"]) ? raw["currency"] : null,
    rows: budgets.flatMap((rows) => rows ?? []),
  }
}
