// apps/web/src/integrations/google_ads/api/refresh-budget-assignment.ts

import { lookupEntityReferences } from "@/components/tool-ui/entity-reference-queries"
import { parseCampaignBudgetReference } from "@/integrations/google_ads/lib/campaign-budgets"
import { parseCampaignReference } from "@/integrations/google_ads/lib/campaigns"
import { googleAdsId } from "@/integrations/google_ads/lib/field-values"
import { isRecord } from "@/lib/guards"
import type { ApprovalDisplayRefresh } from "@/integrations/approval-display-query"

export const refreshBudgetAssignment: ApprovalDisplayRefresh = async (
  args,
  conversationId,
  signal
) => {
  if (
    !isRecord(args) ||
    !Array.isArray(args["campaigns"]) ||
    !args["campaigns"].every(isRecord) ||
    !isRecord(args["destination_budget"])
  )
    throw new Error("Invalid budget selection")
  const selected = args["campaigns"]
  const destinationValue = args["destination_budget"]
  const destination = parseCampaignBudgetReference(destinationValue)
  const campaigns = selected.map(parseCampaignReference)
  if (
    !destination ||
    campaigns.length < 1 ||
    campaigns.length > 50 ||
    campaigns.some((campaign) => !campaign) ||
    selected.some((campaign) => campaign["customer_id"] !== destination.customerId) ||
    new Set(campaigns.map((campaign) => campaign?.campaignId)).size !== campaigns.length
  )
    throw new Error("Invalid budget selection")

  async function resolve(fieldKey: string, exactValues: Record<string, unknown>[]) {
    const response = await lookupEntityReferences(
      {
        conversationId,
        dependentArgs: {},
        exactValues,
        fieldKey,
        toolName: "google_ads_assign_campaign_budgets",
      },
      signal
    )
    return response.choices.map((choice) => choice.value)
  }
  const [liveCampaigns, liveDestinations] = await Promise.all([
    resolve("campaigns", selected),
    resolve("destination_budget", [destinationValue]),
  ])
  const orderedCampaigns = campaigns.map((campaign) =>
    liveCampaigns.find((value) => {
      const reference = parseCampaignReference(value)
      return (
        reference?.campaignId === campaign?.campaignId &&
        value["customer_id"] === destination.customerId
      )
    })
  )
  const liveDestination = liveDestinations.find((value) => {
    const reference = parseCampaignBudgetReference(value)
    return (
      reference?.customerId === destination.customerId &&
      reference.budgetId === destination.budgetId
    )
  })
  if (!liveDestination || orderedCampaigns.some((value) => !value))
    throw new Error("Selected target unavailable")
  const sources = orderedCampaigns.map((value) => {
    const budgetId = value && googleAdsId(value["campaign_budget_id"])
    if (!budgetId) throw new Error("Source budget unavailable")
    return {
      entity_kind: "google_ads_campaign_budget",
      customer_id: destination.customerId,
      budget_id: budgetId,
      label: "Campaign budget",
    }
  })
  const liveSources = await resolve("destination_budget", [
    ...new Map(sources.map((value) => [value.budget_id, value])).values(),
  ])
  const routes = orderedCampaigns.map((campaign, index) => {
    const source = sources[index]
    const previous = liveSources.find((value) => {
      const reference = parseCampaignBudgetReference(value)
      return (
        reference?.customerId === source?.customer_id && reference?.budgetId === source?.budget_id
      )
    })
    if (!previous) throw new Error("Source budget unavailable")
    return { campaign, previous_budget: previous, destination_budget: liveDestination }
  })
  return {
    ...args,
    campaigns: orderedCampaigns,
    destination_budget: liveDestination,
    _budget_routes: routes,
  }
}
