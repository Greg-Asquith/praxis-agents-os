// apps/web/src/integrations/google_ads/presenters/search-targeting.tsx

import { EmptyResult } from "@/components/tool-ui/empty-result"
import { TargetingSearchTable } from "@/integrations/google_ads/components/targeting-search-table"
import { parseTargetingSearch } from "@/integrations/google_ads/lib/targeting-search"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"
import { compactDetails, stringArg, stringDetail } from "@/integrations/tool-details"
import { isRecord } from "@/lib/guards"

const KIND_LABELS: Record<string, string> = { language: "Languages", location: "Locations" }

function searchedNames(args: unknown): string {
  const names = isRecord(args) ? args["names"] : null
  return Array.isArray(names) ? names.filter((name) => typeof name === "string").join(", ") : ""
}

export const googleAdsSearchTargetingPresenter = defineIntegrationReadPresenter(googleAdsProvider, {
  ariaLabel: "Google Ads targeting options",
  emptyLabel: "No Google Ads accounts were queried.",
  heading: "Search Targeting",
  progressLabel: "Searching Google Ads targeting…",
  tool: "google_ads_search_targeting",
  details: (args) => {
    const kind = stringArg(args, "kind")
    const names = searchedNames(args)
    return compactDetails([
      names ? { label: "Search", value: names } : null,
      kind ? { label: "Kind", value: KIND_LABELS[kind] ?? kind } : null,
      stringDetail(args, "country_code", "Country"),
    ])
  },
  parseResult: parseTargetingSearch,
  render: (result, entry, args) => {
    if (result.options.length === 0) {
      const kind = stringArg(args, "kind") === "language" ? "languages" : "locations"
      return (
        <EmptyResult>
          No {kind} match {searchedNames(args)}. Try a broader term.
        </EmptyResult>
      )
    }
    return <TargetingSearchTable accountId={entry.externalId} result={result} />
  },
})
