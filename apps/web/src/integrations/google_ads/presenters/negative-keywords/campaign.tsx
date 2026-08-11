// apps/web/src/integrations/google_ads/presenters/negative-keywords/campaign.tsx

import {
  CampaignNegativeKeywordApprovalSummary,
  CampaignNegativeKeywordOutcome,
  type CampaignNegativeKeywordResult,
} from "@/integrations/google_ads/components/negative-keyword-outcome"
import { createNegativeKeywordPresenter } from "@/integrations/google_ads/presenters/negative-keywords/presenter"
import {
  campaignNegativeKeywordArgs,
  campaignNegativeKeywordResult,
  campaignNegativeKeywordSummary,
} from "@/integrations/google_ads/presenters/negative-keywords/utils"

export const googleAdsCampaignNegativeKeywordsPresenter = createNegativeKeywordPresenter({
  copy: {
    approvalLabel: {
      add: "Add Google Ads Campaign Negative Keywords",
      remove: "Remove Google Ads Campaign Negative Keywords",
    },
    approvalPrompt: {
      add: "Review the campaigns and keyword rows before blocking matching traffic.",
      remove:
        "Review the campaigns and exclusions. Removing them can re-enable traffic and increase spend.",
    },
    approvalTitle: {
      add: "Add Campaign Negative Keywords",
      remove: "Remove Campaign Negative Keywords",
    },
    deniedDescription: {
      add: "This campaign negative keyword change was declined. Nothing was added.",
      remove: "This campaign negative keyword change was declined. Nothing was removed.",
    },
    emptyLabel: "No Google Ads accounts changed campaign negative keywords.",
    failedDescription:
      "The update did not finish. No campaign negative keyword change was confirmed.",
    heading: "Campaign Negative Keywords",
    progressLabel: {
      add: "Adding campaign negative keywords…",
      remove: "Removing campaign negative keywords…",
    },
    resultAriaLabel: "Google Ads campaign negative keyword results",
    resultFailure: "Praxis could not confirm the campaign negative keyword changes.",
    unconfirmedAriaLabel: "Unconfirmed Google Ads campaign negative keyword update",
    waitingLabel: "Waiting for campaign negative keyword approval…",
  },
  key: "google-ads-campaign-negative-keywords",
  parseArgs: campaignNegativeKeywordArgs,
  parseResult: campaignNegativeKeywordResult,
  renderApprovalSummary: (summary) => (
    <CampaignNegativeKeywordApprovalSummary
      campaignCount={summary.campaignCount}
      keywordCount={summary.keywordCount}
    />
  ),
  renderOutcome: (result: CampaignNegativeKeywordResult, removing) => (
    <CampaignNegativeKeywordOutcome action={removing ? "remove" : "add"} result={result} />
  ),
  summarize: campaignNegativeKeywordSummary,
  toolNames: {
    add: "google_ads_add_campaign_negative_keywords",
    remove: "google_ads_remove_campaign_negative_keywords",
  },
})
