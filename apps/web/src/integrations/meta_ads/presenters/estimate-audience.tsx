// apps/web/src/integrations/meta_ads/presenters/estimate-audience.tsx

import { parseMetaAdsAudienceEstimate } from "@/integrations/meta_ads/lib/targeting"
import { targetingSentences } from "@/integrations/meta_ads/lib/targeting-sentence"
import { metaAdsProvider } from "@/integrations/meta_ads/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"
import { isRecord } from "@/lib/guards"

export const metaAdsEstimateAudiencePresenter = defineIntegrationReadPresenter(metaAdsProvider, {
  ariaLabel: "Meta Ads audience estimate",
  emptyLabel: "No Meta Ads accounts were queried.",
  heading: "Estimate Meta Ads Audience",
  progressLabel: "Estimating Meta Ads audience…",
  tool: "meta_ads_estimate_audience",
  parseResult: parseMetaAdsAudienceEstimate,
  render: (result, _entry, args) => {
    const sentences = targetingSentences(isRecord(args) ? args["targeting"] : null)
    return (
      <div className="grid min-w-0 gap-2">
        <p className="text-2xl font-semibold tabular-nums">
          {result.range ?? "No estimate from Meta"}
        </p>
        {sentences.length > 0 ? <p className="text-sm">{sentences.join(" ")}</p> : null}
        {result.notes.map((note) => (
          <p key={note} className="text-muted-foreground text-sm">
            {note}
          </p>
        ))}
      </div>
    )
  },
})
