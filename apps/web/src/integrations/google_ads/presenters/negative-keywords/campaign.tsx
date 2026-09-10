// apps/web/src/integrations/google_ads/presenters/negative-keywords/campaign.tsx

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import {
  CampaignNegativeKeywordApprovalSummary,
  CampaignNegativeKeywordOutcome,
} from "@/integrations/google_ads/components/negative-keyword-outcome"
import {
  campaignNegativeKeywordArgs,
  campaignNegativeKeywordResult,
  campaignNegativeKeywordSummary,
} from "@/integrations/google_ads/presenters/negative-keywords/utils"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const googleAdsCampaignNegativeKeywordsPresenter = createIntegrationWritePresenter({
  key: "google-ads-campaign-negative-keywords",
  variants: {
    google_ads_add_campaign_negative_keywords: defineIntegrationWriteVariant(googleAdsProvider, {
      copy: { verb: "Add", object: "campaign negative keywords", effect: "added" },
      approval: {
        parseArgs: (value) => campaignNegativeKeywordArgs(value, false),
        prompt: "Review the campaigns and keyword rows before blocking matching traffic.",
        renderSummary: (value, fallback) => {
          const summary = campaignNegativeKeywordSummary(value, fallback)
          return (
            <CampaignNegativeKeywordApprovalSummary
              campaignCount={summary.campaignCount}
              keywordCount={summary.keywordCount}
            />
          )
        },
      },
      parseResult: (value) => campaignNegativeKeywordResult(value, false),
      renderOutcome: (result) => <CampaignNegativeKeywordOutcome action="add" result={result} />,
      renderFailure: (args, description) => (
        <GoogleAdsFailureTargets description={description} targets={args?.selectionLabels ?? []} />
      ),
    }),
    google_ads_remove_campaign_negative_keywords: defineIntegrationWriteVariant(googleAdsProvider, {
      copy: { verb: "Remove", object: "campaign negative keywords", effect: "removed" },
      approval: {
        parseArgs: (value) => campaignNegativeKeywordArgs(value, true),
        prompt:
          "Review the campaigns and exclusions. Removing them can re-enable traffic and increase spend.",
        renderSummary: (value, fallback) => {
          const summary = campaignNegativeKeywordSummary(value, fallback)
          return (
            <CampaignNegativeKeywordApprovalSummary
              campaignCount={summary.campaignCount}
              keywordCount={summary.keywordCount}
            />
          )
        },
      },
      parseResult: (value) => campaignNegativeKeywordResult(value, true),
      renderOutcome: (result) => <CampaignNegativeKeywordOutcome action="remove" result={result} />,
      renderFailure: (args, description) => (
        <GoogleAdsFailureTargets description={description} targets={args?.selectionLabels ?? []} />
      ),
    }),
  },
})
