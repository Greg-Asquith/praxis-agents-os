// apps/web/src/integrations/google_ads/presenters/negative-keywords/ad-group.tsx

import {
  AdGroupNegativeKeywordApprovalSummary,
  AdGroupNegativeKeywordOutcome,
  type AdGroupNegativeKeywordResult,
} from "@/integrations/google_ads/components/negative-keyword-outcome"
import { createNegativeKeywordPresenter } from "@/integrations/google_ads/presenters/negative-keywords/presenter"
import {
  adGroupNegativeKeywordArgs,
  adGroupNegativeKeywordResult,
  adGroupNegativeKeywordSummary,
} from "@/integrations/google_ads/presenters/negative-keywords/utils"

export const googleAdsAdGroupNegativeKeywordsPresenter = createNegativeKeywordPresenter({
  copy: {
    approvalLabel: {
      add: "Add Google Ads Ad Group Negative Keywords",
      remove: "Remove Google Ads Ad Group Negative Keywords",
    },
    approvalPrompt: {
      add: "Review the ad groups, campaigns, and keyword rows before blocking matching traffic.",
      remove:
        "Review the ad groups and exclusions. Removing them can re-enable traffic and increase spend.",
    },
    approvalTitle: {
      add: "Add Ad Group Negative Keywords",
      remove: "Remove Ad Group Negative Keywords",
    },
    deniedDescription: {
      add: "This ad group negative keyword change was declined. Nothing was added.",
      remove: "This ad group negative keyword change was declined. Nothing was removed.",
    },
    emptyLabel: "No Google Ads accounts changed ad group negative keywords.",
    failedDescription:
      "The update did not finish. No ad group negative keyword change was confirmed.",
    heading: "Ad Group Negative Keywords",
    progressLabel: {
      add: "Adding ad group negative keywords…",
      remove: "Removing ad group negative keywords…",
    },
    resultAriaLabel: "Google Ads ad group negative keyword results",
    unconfirmedAriaLabel: "Unconfirmed Google Ads ad group negative keyword update",
    waitingLabel: "Waiting for ad group negative keyword approval…",
  },
  key: "google-ads-ad-group-negative-keywords",
  parseArgs: adGroupNegativeKeywordArgs,
  parseResult: adGroupNegativeKeywordResult,
  renderApprovalSummary: (summary) => (
    <AdGroupNegativeKeywordApprovalSummary
      adGroupCount={summary.adGroupCount}
      keywordCount={summary.keywordCount}
      selectionLabels={summary.selectionLabels}
    />
  ),
  renderOutcome: (result: AdGroupNegativeKeywordResult, removing) => (
    <AdGroupNegativeKeywordOutcome action={removing ? "remove" : "add"} result={result} />
  ),
  summarize: adGroupNegativeKeywordSummary,
  toolNames: {
    add: "google_ads_add_ad_group_negative_keywords",
    remove: "google_ads_remove_ad_group_negative_keywords",
  },
})
