// apps/web/src/integrations/google_ads/presenters/remove-campaign-budgets.tsx

import type { GoogleAdsOutcomeColumn as DataColumn } from "@/integrations/google_ads/components/outcome-table"

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import {
  OUTCOMES,
  renderRemovalApprovalSummary,
  renderRemovalOutcomeTable,
  type RemovalArgs,
  type RemovalResult,
  type RemovalResultRow,
} from "@/integrations/google_ads/components/remove-campaign-budgets"
import {
  campaignBudgetIdentity,
  parseCampaignBudgetReference,
  type CampaignBudgetWithCurrency,
} from "@/integrations/google_ads/lib/campaign-budgets"
import { parseOutcomeEnvelope } from "@/integrations/google_ads/lib/envelopes"
import { googleAdsWriteCopy } from "@/integrations/google_ads/lib/copy"
import {
  createGoogleAdsWritePresenter,
  defineGoogleAdsWriteVariant,
} from "@/integrations/google_ads/presenters/write-presenter"
import { isNullableString, isRecord } from "@/lib/guards"

const COLUMNS: DataColumn[] = [
  { key: "budget", kind: "text", label: "Budget" },
  { key: "budgetId", kind: "id", label: "Budget ID" },
  { key: "amount", kind: "text", label: "Amount", align: "right" },
  { key: "period", kind: "text", label: "Period" },
  { key: "linkedCampaigns", kind: "text", label: "Linked Campaigns" },
  { key: "previousStatus", kind: "status", label: "Before" },
  { key: "resultingStatus", kind: "status", label: "After" },
]

const copy = googleAdsWriteCopy({
  verb: "Remove",
  object: "campaign budgets",
  effect: "removed",
  destructive: true,
})

export const googleAdsRemoveCampaignBudgetsPresenter = createGoogleAdsWritePresenter({
  key: "google-ads-remove-campaign-budgets",
  variants: {
    google_ads_remove_campaign_budgets: defineGoogleAdsWriteVariant({
      ...copy,
      approval: {
        ...copy.approval,
        parseArgs: removalArgs,
        prompt: "These unused campaign budgets are permanently removed from Google Ads.",
        renderSummary: (value, fallback) =>
          renderRemovalApprovalSummary(removalArgs(value) ?? fallback),
      },
      details: (args) => (args ? [{ label: "Budgets", value: String(args.budgets.length) }] : []),
      parseResult: removalResult,
      renderFailure: (args, description) => (
        <GoogleAdsFailureTargets
          description={description}
          targets={args?.budgets.map((budget) => budget.label) ?? []}
        />
      ),
      renderOutcome: (result) => renderRemovalOutcomeTable(result, COLUMNS),
    }),
  },
})

function removalArgs(value: unknown): RemovalArgs | null {
  if (!isRecord(value) || !Array.isArray(value["budgets"]) || value["budgets"].length === 0) {
    return null
  }
  const budgets: CampaignBudgetWithCurrency[] = []
  const budgetIds = new Set<string>()
  for (const valueBudget of value["budgets"]) {
    const budget = parseCampaignBudgetReference(valueBudget)
    const identity = budget ? campaignBudgetIdentity(budget) : null
    if (
      !budget?.currencyCode ||
      budget.referenceCount !== 0 ||
      identity === null ||
      budgetIds.has(identity)
    ) {
      return null
    }
    budgetIds.add(identity)
    budgets.push({ ...budget, currencyCode: budget.currencyCode })
  }
  return { budgets }
}

function removalResult(value: unknown): RemovalResult | null {
  const envelope = parseOutcomeEnvelope(value, OUTCOMES, parseResultRow)
  if (!envelope) return null
  return { counts: envelope.counts, rows: envelope.rows, samplesTruncated: envelope.truncated }
}

function parseResultRow(
  sample: unknown,
  outcome: (typeof OUTCOMES)[number]
): RemovalResultRow | null {
  if (
    !isRecord(sample) ||
    sample["outcome"] !== outcome ||
    typeof sample["previous_status"] !== "string" ||
    !isNullableString(sample["resulting_status"] ?? null) ||
    !isNullableString(sample["error_code"] ?? null) ||
    !isNullableString(sample["message"] ?? null)
  ) {
    return null
  }
  const reference = parseCampaignBudgetReference(sample["reference"])
  if (!reference?.currencyCode) {
    return null
  }
  return {
    errorCode: typeof sample["error_code"] === "string" ? sample["error_code"] : null,
    message: typeof sample["message"] === "string" ? sample["message"] : null,
    outcome,
    previousStatus: sample["previous_status"],
    reference: { ...reference, currencyCode: reference.currencyCode },
    resultingStatus:
      typeof sample["resulting_status"] === "string" ? sample["resulting_status"] : null,
  }
}
