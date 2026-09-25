// apps/web/src/integrations/meta_ads/presenters/objects.tsx

import { EmptyResult } from "@/components/tool-ui/empty-result"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import { parseMetaAdsObjects } from "@/integrations/meta_ads/lib/read-models"
import { metaAdsProvider } from "@/integrations/meta_ads/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"
import { compactDetails, listDetail, stringDetail } from "@/integrations/tool-details"
import { formatCurrencyAmount, titleCaseToken } from "@/lib/format"

const columns: DataColumn[] = [
  { key: "name", label: "Name", kind: "text" },
  { key: "status", label: "Status", kind: "status" },
  { key: "effective_status", label: "Delivery status", kind: "status" },
  { key: "budget", label: "Budget", kind: "text" },
  { key: "budget_remaining", label: "Budget remaining", kind: "text" },
  { key: "bid_strategy", label: "Bid strategy", kind: "text" },
  { key: "bid_amount", label: "Bid amount", kind: "currency" },
  { key: "start_time", label: "Start", kind: "datetime" },
  { key: "end_time", label: "End", kind: "datetime" },
  { key: "objective", label: "Objective", kind: "text" },
  { key: "optimization_goal", label: "Optimisation goal", kind: "text" },
  { key: "id", label: "ID", kind: "id" },
  { key: "campaign_id", label: "Campaign ID", kind: "id" },
  { key: "adset_id", label: "Ad set ID", kind: "id" },
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
    return result.objects.length > 0 ? (
      <DataTable
        columns={columns.map((column) => ({ ...column, currencyCode: result.currency }))}
        rows={result.objects.map((object) => ({
          ...object,
          name: object.name ?? "Unnamed object",
          budget:
            object.budget?.kind === "campaign"
              ? "Set at campaign level"
              : object.budget
                ? `${money(object.budget.amount)} ${object.budget.kind}`
                : null,
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
        }))}
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
