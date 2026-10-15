// apps/web/src/integrations/meta_ads/presenters/search-targeting.tsx

import { EmptyResult } from "@/components/tool-ui/empty-result"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import {
  parseMetaAdsTargetingSearch,
  TARGETING_KIND_LABELS,
} from "@/integrations/meta_ads/lib/targeting"
import { metaAdsProvider } from "@/integrations/meta_ads/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"
import { compactDetails, stringArg, stringDetail } from "@/integrations/tool-details"

const columns: DataColumn[] = [
  { key: "name", label: "Name", kind: "text" },
  { key: "kind", label: "Kind", kind: "text" },
  { key: "size", label: "Audience Size", kind: "text", align: "right" },
  { key: "description", label: "Details", kind: "text" },
  { key: "key", label: "Key", kind: "id", hidden: true },
]

export const metaAdsSearchTargetingPresenter = defineIntegrationReadPresenter(metaAdsProvider, {
  ariaLabel: "Meta Ads targeting options",
  emptyLabel: "No Meta Ads accounts were queried.",
  heading: "Search Meta Ads Targeting",
  progressLabel: "Searching Meta Ads targeting…",
  tool: "meta_ads_search_targeting",
  details: (args) => {
    const kind = stringArg(args, "kind")
    return compactDetails([
      stringDetail(args, "query", "Search", true),
      kind ? { label: "Kind", value: TARGETING_KIND_LABELS[kind] ?? kind } : null,
      stringDetail(args, "country_code", "Country"),
    ])
  },
  parseResult: parseMetaAdsTargetingSearch,
  render: (result, entry) =>
    result.options.length > 0 ? (
      <DataTable
        columns={columns}
        rows={result.options.map((option) => ({
          ...option,
          kind: TARGETING_KIND_LABELS[option.kind] ?? option.kind,
        }))}
        pageSize={25}
        exportFilename={`meta-ads-${entry.externalId}-targeting.csv`}
        truncationNote={result.truncated ? "Meta has more matches. Search more precisely." : null}
      />
    ) : (
      <EmptyResult>No targeting options match this search.</EmptyResult>
    ),
})
