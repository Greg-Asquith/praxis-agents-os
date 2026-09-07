// apps/web/src/integrations/google_ads/presenters/negative-keywords/campaign.tsx

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import {
  CampaignNegativeKeywordApprovalSummary,
  CampaignNegativeKeywordOutcome,
} from "@/integrations/google_ads/components/negative-keyword-outcome"
import { googleAdsWriteCopy } from "@/integrations/google_ads/lib/copy"
import {
  campaignNegativeKeywordArgs,
  campaignNegativeKeywordResult,
  campaignNegativeKeywordSummary,
} from "@/integrations/google_ads/presenters/negative-keywords/utils"
import {
  createGoogleAdsWritePresenter,
  defineGoogleAdsWriteVariant,
} from "@/integrations/google_ads/presenters/write-presenter"

const addCopy = googleAdsWriteCopy({
  verb: "Add",
  object: "campaign negative keywords",
  effect: "added",
})
const removeCopy = googleAdsWriteCopy({
  verb: "Remove",
  object: "campaign negative keywords",
  effect: "removed",
})

export const googleAdsCampaignNegativeKeywordsPresenter = createGoogleAdsWritePresenter({
  key: "google-ads-campaign-negative-keywords",
  variants: {
    google_ads_add_campaign_negative_keywords: defineGoogleAdsWriteVariant({
      ...addCopy,
      approval: {
        ...addCopy.approval,
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
    google_ads_remove_campaign_negative_keywords: defineGoogleAdsWriteVariant({
      ...removeCopy,
      approval: {
        ...removeCopy.approval,
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
