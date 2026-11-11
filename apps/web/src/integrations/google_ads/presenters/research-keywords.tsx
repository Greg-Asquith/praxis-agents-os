// apps/web/src/integrations/google_ads/presenters/research-keywords.tsx

import { EmptyResult } from "@/components/tool-ui/empty-result"
import { ResearchKeywordsTable } from "@/integrations/google_ads/components/research-keywords-table"
import { parseKeywordResearch } from "@/integrations/google_ads/lib/research-keywords"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"
import { compactDetails, stringDetail } from "@/integrations/tool-details"
import { isRecord } from "@/lib/guards"

function listDetail(args: unknown, key: string, label: string) {
  const values = isRecord(args) ? args[key] : null
  const text = Array.isArray(values)
    ? values.filter((value) => typeof value === "string").join(", ")
    : ""
  return text ? { label, value: text } : null
}

export const googleAdsResearchKeywordsPresenter = defineIntegrationReadPresenter(
  googleAdsProvider,
  {
    ariaLabel: "Google Ads keyword ideas",
    emptyLabel: "No Google Ads accounts were queried.",
    heading: "Research Keywords",
    progressLabel: "Researching keywords…",
    tool: "google_ads_research_keywords",
    details: (args) =>
      compactDetails([
        listDetail(args, "seeds", "Seeds"),
        stringDetail(args, "url", "Website"),
        listDetail(args, "keywords", "Keywords"),
      ]),
    parseResult: parseKeywordResearch,
    render: (result) =>
      result.ideas.length === 0 ? (
        <EmptyResult>Google has no keyword ideas for this. Try broader seeds.</EmptyResult>
      ) : (
        <ResearchKeywordsTable result={result} />
      ),
  }
)
