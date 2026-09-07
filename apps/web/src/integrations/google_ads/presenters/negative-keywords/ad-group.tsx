// apps/web/src/integrations/google_ads/presenters/negative-keywords/ad-group.tsx

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import {
  AdGroupNegativeKeywordApprovalSummary,
  AdGroupNegativeKeywordOutcome,
} from "@/integrations/google_ads/components/negative-keyword-outcome"
import { googleAdsWriteCopy } from "@/integrations/google_ads/lib/copy"
import {
  adGroupNegativeKeywordArgs,
  adGroupNegativeKeywordResult,
  adGroupNegativeKeywordSummary,
} from "@/integrations/google_ads/presenters/negative-keywords/utils"
import {
  createGoogleAdsWritePresenter,
  defineGoogleAdsWriteVariant,
} from "@/integrations/google_ads/presenters/write-presenter"

const addCopy = googleAdsWriteCopy({
  verb: "Add",
  object: "ad group negative keywords",
  effect: "added",
})
const removeCopy = googleAdsWriteCopy({
  verb: "Remove",
  object: "ad group negative keywords",
  effect: "removed",
})

export const googleAdsAdGroupNegativeKeywordsPresenter = createGoogleAdsWritePresenter({
  key: "google-ads-ad-group-negative-keywords",
  variants: {
    google_ads_add_ad_group_negative_keywords: defineGoogleAdsWriteVariant({
      ...addCopy,
      approval: {
        ...addCopy.approval,
        parseArgs: (value) => adGroupNegativeKeywordArgs(value, false),
        prompt: "Review the ad groups, campaigns, keyword rows before blocking matching traffic.",
        renderSummary: (value, fallback) => {
          const summary = adGroupNegativeKeywordSummary(value, fallback)
          return (
            <AdGroupNegativeKeywordApprovalSummary
              adGroupCount={summary.adGroupCount}
              keywordCount={summary.keywordCount}
              selectionLabels={summary.selectionLabels}
            />
          )
        },
      },
      parseResult: (value) => adGroupNegativeKeywordResult(value, false),
      renderOutcome: (result) => <AdGroupNegativeKeywordOutcome action="add" result={result} />,
      renderFailure: (args, description) => (
        <GoogleAdsFailureTargets description={description} targets={args?.selectionLabels ?? []} />
      ),
    }),
    google_ads_remove_ad_group_negative_keywords: defineGoogleAdsWriteVariant({
      ...removeCopy,
      approval: {
        ...removeCopy.approval,
        parseArgs: (value) => adGroupNegativeKeywordArgs(value, true),
        prompt:
          "Review the ad groups and exclusions. Removing them can re-enable traffic and increase spend.",
        renderSummary: (value, fallback) => {
          const summary = adGroupNegativeKeywordSummary(value, fallback)
          return (
            <AdGroupNegativeKeywordApprovalSummary
              adGroupCount={summary.adGroupCount}
              keywordCount={summary.keywordCount}
              selectionLabels={summary.selectionLabels}
            />
          )
        },
      },
      parseResult: (value) => adGroupNegativeKeywordResult(value, true),
      renderOutcome: (result) => <AdGroupNegativeKeywordOutcome action="remove" result={result} />,
      renderFailure: (args, description) => (
        <GoogleAdsFailureTargets description={description} targets={args?.selectionLabels ?? []} />
      ),
    }),
  },
})
