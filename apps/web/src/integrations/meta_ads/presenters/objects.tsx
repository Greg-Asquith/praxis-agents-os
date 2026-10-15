// apps/web/src/integrations/meta_ads/presenters/objects.tsx

import { EmptyResult } from "@/components/tool-ui/empty-result"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import { parseMetaAdsObjects } from "@/integrations/meta_ads/lib/read-models"
import { metaAdsProvider } from "@/integrations/meta_ads/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"
import { compactDetails, listDetail, stringDetail } from "@/integrations/tool-details"
import { formatCurrencyAmount, titleCaseToken } from "@/lib/format"

function budgetLabel(
  budget: { kind: string; amount: string | null } | null,
  money: (amount: string | null) => string
): string | null {
  if (!budget) return null
  if (budget.kind === "campaign") return "Set at campaign level"
  return `${money(budget.amount)} ${budget.kind}`
}

const columns: DataColumn[] = [
  { key: "name", label: "Name", kind: "text" },
  { key: "status", label: "Status", kind: "status" },
  { key: "effective_status", label: "Delivery Status", kind: "status" },
  { key: "budget", label: "Budget", kind: "text" },
  { key: "review", label: "Review Notes", kind: "text" },
  { key: "objective", label: "Objective", kind: "text" },
  { key: "budget_remaining", label: "Budget Remaining", kind: "text", hidden: true },
  { key: "bid_strategy", label: "Bid Strategy", kind: "text", hidden: true },
  { key: "bid_amount", label: "Bid Amount", kind: "currency", hidden: true },
  { key: "start_time", label: "Start", kind: "datetime", hidden: true },
  { key: "end_time", label: "End", kind: "datetime", hidden: true },
  { key: "optimization_goal", label: "Optimisation Goal", kind: "text", hidden: true },
  { key: "id", label: "ID", kind: "id", hidden: true },
  { key: "campaign_id", label: "Campaign ID", kind: "id", hidden: true },
  { key: "adset_id", label: "Ad Set ID", kind: "id", hidden: true },
]

export const metaAdsObjectsPresenter = defineIntegrationReadPresenter(metaAdsProvider, {
  ariaLabel: "Meta Ads objects",
  emptyLabel: "No Meta Ads accounts were queried.",
  heading: "List Meta Ads objects",
  progressLabel: "Loading Meta Ads objects…",
  tool: "meta_ads_list_objects",
  details: (args) =>
    compactDetails([
      stringDetail(args, "object_type", "Type"),
      listDetail(args, "statuses", "Delivery status", (value) => titleCaseToken(value, value)),
      listDetail(args, "campaign_ids", "Campaign IDs"),
      listDetail(args, "adset_ids", "Ad set IDs"),
      stringDetail(args, "name_contains", "Name contains"),
    ]),
  parseResult: parseMetaAdsObjects,
  render: (result, entry) => {
    const money = (amount: string | null) =>
      amount === null ? "—" : formatCurrencyAmount(amount, result.currency)
    const rows = result.objects.map((object) => ({
      ...object,
      name: object.name ?? "Unnamed object",
      budget: budgetLabel(object.budget, money),
      budget_remaining: object.budget ? money(object.budget.remaining) : null,
      bid_strategy: object.bid_strategy
        ? titleCaseToken(object.bid_strategy.toLowerCase(), object.bid_strategy)
        : null,
      objective: object.objective
        ? titleCaseToken(object.objective.toLowerCase(), object.objective)
        : null,
      optimization_goal: object.optimization_goal
        ? titleCaseToken(object.optimization_goal.toLowerCase(), object.optimization_goal)
        : null,
      review: [...(object.review_reasons ?? []), ...(object.issues ?? [])].join(" ") || null,
    }))
    // Review notes only apply to ads, so the column stays out of the way otherwise.
    const hasReview = rows.some((row) => row.review)
    return rows.length > 0 ? (
      <DataTable
        columns={columns.map((column) => ({
          ...column,
          currencyCode: result.currency,
          hidden: (column.hidden ?? false) || (column.key === "review" && !hasReview),
        }))}
        rows={rows}
        pageSize={25}
        exportFilename={`meta-ads-${entry.externalId}-${result.object_type}.csv`}
        truncationNote={
          result.truncated ? "More objects are available. Narrow the filters to see more." : null
        }
      />
    ) : (
      <EmptyResult>
        {result.truncated
          ? "No objects were returned before the retrieval limit. Narrow the filters and try again."
          : "No objects matched the filters."}
      </EmptyResult>
    )
  },
})
