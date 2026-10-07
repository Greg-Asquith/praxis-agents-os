// apps/web/src/integrations/meta_ads/presenters/list-assets.tsx

import { EmptyResult } from "@/components/tool-ui/empty-result"
import { AssetSection } from "@/integrations/meta_ads/components/asset-section"
import {
  ASSET_SECTIONS,
  emptyAssetsMessage,
  parseMetaAdsAssets,
} from "@/integrations/meta_ads/lib/assets"
import { metaAdsProvider } from "@/integrations/meta_ads/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"
import { compactDetails, listDetail } from "@/integrations/tool-details"
import { titleCaseToken } from "@/lib/format"

export const metaAdsListAssetsPresenter = defineIntegrationReadPresenter(metaAdsProvider, {
  ariaLabel: "Meta Ads Pages and media",
  emptyLabel: "No Meta Ads accounts were queried.",
  heading: "List Meta Ads Pages and Media",
  progressLabel: "Loading Meta Ads Pages and media…",
  tool: "meta_ads_list_assets",
  details: (args) =>
    compactDetails([listDetail(args, "kinds", "Kinds", (value) => titleCaseToken(value, value))]),
  parseResult: parseMetaAdsAssets,
  render: (result, entry, args) => (
    <div className="grid min-w-0 gap-4">
      {result.notes.length > 0 ? (
        <ul className="text-muted-foreground grid gap-1 text-xs">
          {result.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
      {ASSET_SECTIONS.some((section) => result[section.kind].length > 0) ? (
        ASSET_SECTIONS.map((section) => (
          <AssetSection
            key={section.kind}
            exportFilename={`meta-ads-${entry.externalId}-${section.kind}.csv`}
            result={result}
            section={section}
          />
        ))
      ) : (
        <EmptyResult>{emptyAssetsMessage(result, args)}</EmptyResult>
      )}
    </div>
  ),
})
