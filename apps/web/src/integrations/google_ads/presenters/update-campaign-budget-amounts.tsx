// apps/web/src/integrations/google_ads/presenters/update-campaign-budget-amounts.tsx

import type { GoogleAdsOutcomeColumn as DataColumn } from "@/integrations/google_ads/components/outcome-table"

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import {
  type BudgetAmountOutcome,
  type BudgetAmountResult,
  type BudgetAmountUpdate,
  OUTCOMES,
  renderUpdateBudgetApprovalSummary,
  renderUpdateBudgetOutcome,
  type UpdateBudgetArgs,
  type UpdateBudgetResult,
} from "@/integrations/google_ads/components/update-campaign-budget-amounts"
import {
  campaignBudgetIdentity,
  parseCampaignBudgetReference,
} from "@/integrations/google_ads/lib/campaign-budgets"
import { parseOutcomeEnvelope } from "@/integrations/google_ads/lib/envelopes"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"
import { isNullableString, isRecord, parsePositiveDecimal } from "@/lib/guards"

const COLUMNS: DataColumn[] = [
  { key: "budget", kind: "text", label: "Budget" },
  { key: "previous", kind: "text", label: "Before", align: "right" },
  { key: "requested", kind: "text", label: "Requested", align: "right" },
  { key: "after", kind: "text", label: "After", align: "right" },
  { key: "change", kind: "text", label: "Requested change", width: 180 },
  { key: "period", kind: "text", label: "Period" },
  { key: "linkedCampaigns", kind: "text", label: "Linked Campaigns" },
]

export const googleAdsUpdateCampaignBudgetAmountsPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_update_campaign_budget_amounts: defineIntegrationWriteVariant(googleAdsProvider, {
      copy: { verb: "Update", object: "campaign budget amounts", effect: "updated" },
      approval: {
        parseArgs: updateBudgetArgs,
        prompt: "Review each selected budget amount before changing live spend limits.",
        renderSummary: (value, fallback) =>
          renderUpdateBudgetApprovalSummary(updateBudgetArgs(value) ?? fallback),
      },
      details: (args) => (args ? [{ label: "Budgets", value: String(args.updates.length) }] : []),
      parseResult: updateBudgetResult,
      renderFailure: (args, description) => (
        <GoogleAdsFailureTargets
          description={description}
          targets={args?.updates.map((update) => update.budget.label) ?? []}
        />
      ),
      renderOutcome: (result) => renderUpdateBudgetOutcome(result, COLUMNS),
    }),
  },
})

function updateBudgetArgs(value: unknown): UpdateBudgetArgs | null {
  if (!isRecord(value) || !Array.isArray(value["updates"]) || value["updates"].length === 0) {
    return null
  }
  const updates: BudgetAmountUpdate[] = []
  const identities = new Set<string>()
  for (const item of value["updates"]) {
    if (!isRecord(item)) {
      return null
    }
    const budget = parseCampaignBudgetReference(item["budget"])
    const amount = parsePositiveDecimal(item["amount"])
    const identity = budget ? campaignBudgetIdentity(budget) : null
    const currentAmountAvailable =
      budget?.period === "DAILY"
        ? budget.amountMicros !== null
        : budget?.period === "CUSTOM_PERIOD"
          ? budget.totalAmountMicros !== null
          : false
    if (
      !budget?.currencyCode ||
      !amount ||
      identity === null ||
      !currentAmountAvailable ||
      identities.has(identity)
    ) {
      return null
    }
    identities.add(identity)
    updates.push({ amount, budget: { ...budget, currencyCode: budget.currencyCode } })
  }
  return { updates }
}

function updateBudgetResult(value: unknown): UpdateBudgetResult | null {
  if (!isRecord(value) || typeof value["campaign_labels_truncated"] !== "boolean") return null
  const envelope = parseOutcomeEnvelope(value, OUTCOMES, budgetAmountRow)
  if (!envelope) return null
  return {
    campaignLabelsTruncated: value["campaign_labels_truncated"],
    counts: envelope.counts,
    rows: envelope.rows,
    samplesTruncated: envelope.truncated,
  }
}

function budgetAmountRow(
  value: unknown,
  expectedOutcome: BudgetAmountOutcome
): BudgetAmountResult | null {
  if (
    !isRecord(value) ||
    value["outcome"] !== expectedOutcome ||
    typeof value["campaign_label_count"] !== "number" ||
    !Number.isSafeInteger(value["campaign_label_count"]) ||
    value["campaign_label_count"] < 0 ||
    typeof value["campaign_labels_truncated"] !== "boolean"
  ) {
    return null
  }
  const reference = parseCampaignBudgetReference(value["reference"])
  const previousAmount = parsePositiveDecimal(value["previous_amount"])
  const requestedAmount = parsePositiveDecimal(value["requested_amount"])
  if (
    !reference?.currencyCode ||
    !previousAmount ||
    !requestedAmount ||
    !isNullableString(value["error_code"] ?? null) ||
    !isNullableString(value["message"] ?? null)
  ) {
    return null
  }
  return {
    campaignLabelCount: value["campaign_label_count"],
    campaignLabelsTruncated: value["campaign_labels_truncated"],
    errorCode: typeof value["error_code"] === "string" ? value["error_code"] : null,
    message: typeof value["message"] === "string" ? value["message"] : null,
    outcome: expectedOutcome,
    previousAmount,
    reference: { ...reference, currencyCode: reference.currencyCode },
    requestedAmount,
  }
}
