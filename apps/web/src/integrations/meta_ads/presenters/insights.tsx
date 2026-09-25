// apps/web/src/integrations/meta_ads/presenters/insights.tsx

import { MetaAdsInsightsResults } from "@/integrations/meta_ads/components/insights-results"
import { parseMetaAdsInsights } from "@/integrations/meta_ads/lib/insights-model"
import { insightsDetails } from "@/integrations/meta_ads/lib/tool-details"
import { metaAdsProvider } from "@/integrations/meta_ads/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"
import type { ToolRowPresenter } from "@/integrations/contract"
import { MetaAdsInsightsApproval } from "@/integrations/meta_ads/components/insights-approval"

const resultsPresenter = defineIntegrationReadPresenter(metaAdsProvider, {
  ariaLabel: "Meta Ads Insights results",
  details: insightsDetails,
  emptyLabel: "No Meta Ads accounts were queried.",
  heading: "Run Meta Ads Insights",
  parseResult: parseMetaAdsInsights,
  progressLabel: "Running Meta Ads Insights…",
  render: (report, entry) => (
    <MetaAdsInsightsResults report={report} externalId={entry.externalId} />
  ),
  tool: "meta_ads_run_insights",
})

export const metaAdsInsightsPresenter: ToolRowPresenter = {
  ...resultsPresenter,
  handlesApprovals: true,
  render: (props) =>
    props.approvalDecision ? (
      <MetaAdsInsightsApproval
        activity={props.activity}
        controls={props.approvalDecision}
        formSchema={props.ui?.form_schema}
      />
    ) : (
      resultsPresenter.render(props)
    ),
}
