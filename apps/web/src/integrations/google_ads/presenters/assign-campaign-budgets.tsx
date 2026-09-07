// apps/web/src/integrations/google_ads/presenters/assign-campaign-budgets.tsx

import type { GoogleAdsOutcomeColumn as DataColumn } from "@/integrations/google_ads/components/outcome-table"
import {
  OUTCOMES,
  renderAssignmentApprovalSummary,
  renderAssignmentOutcomeTable,
  type AssignmentArgs,
  type AssignmentResult,
  type AssignmentResultRow,
  type AssignmentRoute,
} from "@/integrations/google_ads/components/assign-campaign-budgets"
import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import { parseCampaignBudgetReference } from "@/integrations/google_ads/lib/campaign-budgets"
import {
  parseCampaignReference,
  type CampaignReference,
} from "@/integrations/google_ads/lib/campaigns"
import { googleAdsWriteCopy } from "@/integrations/google_ads/lib/copy"
import {
  createGoogleAdsWritePresenter,
  defineGoogleAdsWriteVariant,
} from "@/integrations/google_ads/presenters/write-presenter"
import { isNonNegativeInteger, isNullableString, isRecord } from "@/lib/guards"

const COLUMNS: DataColumn[] = [
  { key: "campaign", kind: "text", label: "Campaign" },
  { key: "campaignId", kind: "id", label: "Campaign ID" },
  { key: "previousBudget", kind: "text", label: "Before" },
  { key: "requestedBudget", kind: "text", label: "After" },
]

const copy = googleAdsWriteCopy({ verb: "Assign", object: "campaign budgets", effect: "assigned" })

export const googleAdsAssignCampaignBudgetsPresenter = createGoogleAdsWritePresenter({
  key: "google-ads-assign-campaign-budgets",
  variants: {
    google_ads_assign_campaign_budgets: defineGoogleAdsWriteVariant({
      ...copy,
      approval: {
        ...copy.approval,
        parseArgs: assignmentArgs,
        prompt: "Review every campaign route before replacing its live campaign budget.",
        renderSummary: (value, fallback) =>
          renderAssignmentApprovalSummary(assignmentArgs(value) ?? fallback),
      },
      details: (args) =>
        args
          ? [
              { label: "Destination", value: args.destination.label },
              { label: "Campaigns", value: String(args.campaigns.length) },
            ]
          : [],
      parseResult: assignmentResult,
      renderFailure: (args, description) => (
        <GoogleAdsFailureTargets
          description={description}
          targets={args?.campaigns.map((campaign) => campaign.label) ?? []}
        />
      ),
      renderOutcome: (result) => renderAssignmentOutcomeTable(result, COLUMNS),
    }),
  },
})

function assignmentArgs(value: unknown): AssignmentArgs | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["campaigns"]) ||
    value["campaigns"].length === 0 ||
    !Array.isArray(value["_budget_routes"])
  ) {
    return null
  }
  const destination = parseCampaignBudgetReference(value["destination_budget"])
  if (!destination) {
    return null
  }
  const campaigns: CampaignReference[] = []
  const campaignIds = new Set<string>()
  for (const valueCampaign of value["campaigns"]) {
    const campaign = parseCampaignReference(valueCampaign)
    if (!campaign || campaignIds.has(campaign.campaignId)) {
      return null
    }
    campaignIds.add(campaign.campaignId)
    campaigns.push(campaign)
  }
  const routes: AssignmentRoute[] = []
  for (const routeValue of value["_budget_routes"]) {
    if (!isRecord(routeValue)) {
      return null
    }
    const campaign = parseCampaignReference(routeValue["campaign"])
    const previousBudget = parseCampaignBudgetReference(routeValue["previous_budget"])
    const destinationBudget = parseCampaignBudgetReference(routeValue["destination_budget"])
    if (!campaign || !previousBudget || !destinationBudget) {
      return null
    }
    routes.push({ campaign, destinationBudget, previousBudget })
  }
  if (
    routes.length !== campaigns.length ||
    routes.some(
      (route, index) =>
        route.campaign.campaignId !== campaigns[index]?.campaignId ||
        route.destinationBudget.customerId !== destination.customerId ||
        route.destinationBudget.budgetId !== destination.budgetId
    )
  ) {
    return null
  }
  return { campaigns, destination, routes }
}

function assignmentResult(value: unknown): AssignmentResult | null {
  if (
    !isRecord(value) ||
    !isRecord(value["counts"]) ||
    !isRecord(value["samples"]) ||
    typeof value["samples_truncated"] !== "boolean"
  ) {
    return null
  }
  const destination = parseCampaignBudgetReference(value["destination_budget"])
  const counts = value["counts"]
  if (
    !destination ||
    !isNonNegativeInteger(counts["assigned"]) ||
    !isNonNegativeInteger(counts["already_set"]) ||
    !isNonNegativeInteger(counts["failed"]) ||
    !isNonNegativeInteger(counts["unverified"])
  ) {
    return null
  }
  const rows: AssignmentResultRow[] = []
  for (const outcome of OUTCOMES) {
    const samples = value["samples"][outcome]
    if (!Array.isArray(samples)) {
      return null
    }
    for (const sample of samples) {
      if (!isRecord(sample) || sample["outcome"] !== outcome) {
        return null
      }
      const campaign = parseCampaignReference(sample["campaign"])
      const previousBudget = parseCampaignBudgetReference(sample["previous_budget"])
      const requestedBudget = parseCampaignBudgetReference(sample["requested_budget"])
      if (
        !campaign ||
        !previousBudget ||
        !requestedBudget ||
        !isNullableString(sample["error_code"] ?? null) ||
        !isNullableString(sample["message"] ?? null)
      ) {
        return null
      }
      rows.push({
        campaign,
        errorCode: typeof sample["error_code"] === "string" ? sample["error_code"] : null,
        message: typeof sample["message"] === "string" ? sample["message"] : null,
        outcome,
        previousBudget,
        requestedBudget,
      })
    }
  }
  const parsedCounts = {
    already_set: counts["already_set"],
    assigned: counts["assigned"],
    failed: counts["failed"],
    unverified: counts["unverified"],
  }
  if (
    !value["samples_truncated"] &&
    rows.length !==
      parsedCounts.assigned +
        parsedCounts.already_set +
        parsedCounts.failed +
        parsedCounts.unverified
  ) {
    return null
  }
  return { counts: parsedCounts, destination, rows, samplesTruncated: value["samples_truncated"] }
}
