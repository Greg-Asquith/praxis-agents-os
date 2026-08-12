// apps/web/src/integrations/google_ads/presenters/negative-keywords/list.tsx

import {
  NegativeKeywordApprovalSummary,
  NegativeKeywordOutcome,
  NegativeKeywordRemovalOutcome,
  type NegativeKeywordRemovalResult,
  type NegativeKeywordResult,
} from "@/integrations/google_ads/components/negative-keyword-outcome"
import {
  listNegativeKeywordApprovalSummary,
  listNegativeKeywordArgs,
  listNegativeKeywordResult,
} from "@/integrations/google_ads/presenters/negative-keywords/utils"
import {
  createGoogleAdsWritePresenter,
  defineGoogleAdsWriteVariant,
} from "@/integrations/google_ads/presenters/write-presenter"

export const googleAdsListNegativeKeywordsPresenter = createGoogleAdsWritePresenter({
  key: "google-ads-list-negative-keywords",
  variants: {
    google_ads_add_negative_keywords: defineGoogleAdsWriteVariant({
      approval: {
        approveLabel: "Approve & Add",
        label: "Add Google Ads Negative Keywords",
        parseArgs: (value) => listNegativeKeywordArgs(value, false),
        prompt: "Review the target list and keyword rows before changing live ad delivery.",
        renderSummary: (value, fallback) => {
          const summary = listNegativeKeywordApprovalSummary(value, fallback, false)
          return (
            <NegativeKeywordApprovalSummary
              includeAny={false}
              keywords={summary.keywords}
              listName={summary.listName}
              total={summary.total}
            />
          )
        },
        title: "Add Negative Keywords",
      },
      deniedDescription: "This negative keyword change was declined. Nothing was added.",
      emptyLabel: "No Google Ads accounts added negative keywords.",
      failedDescription: "The update did not finish. No negative keyword change was confirmed.",
      heading: "Add Negative Keywords",
      malformedDescription:
        "The system couldn't verify this account's negative keyword outcomes. Check the Google Ads platform before taking further action.",
      parseResult: (value): NegativeKeywordResult | null => listNegativeKeywordResult(value, false),
      progressLabel: "Adding Google Ads negative keywords…",
      renderOutcome: (result) => <NegativeKeywordOutcome result={result} />,
      resultAriaLabel: "Google Ads negative keyword results",
      resultFailure:
        "The system couldn't verify the negative keyword changes. Check the Google Ads platform before taking further action.",
      unconfirmedAriaLabel: "Unconfirmed Google Ads negative keyword update",
      unverifiedDescription:
        "The system couldn't verify whether Google Ads added these negative keywords. Check the Google Ads platform before taking further action.",
      waitingLabel: "Waiting for negative keyword approval…",
    }),
    google_ads_remove_negative_keywords: defineGoogleAdsWriteVariant({
      approval: {
        approveLabel: "Approve & Remove",
        label: "Remove Google Ads Negative Keywords",
        parseArgs: (value) => listNegativeKeywordArgs(value, true),
        prompt:
          "Review the target list and keyword rows. Removing them re-enables matching traffic.",
        renderSummary: (value, fallback) => {
          const summary = listNegativeKeywordApprovalSummary(value, fallback, true)
          return (
            <NegativeKeywordApprovalSummary
              includeAny
              keywords={summary.keywords}
              listName={summary.listName}
              total={summary.total}
            />
          )
        },
        title: "Remove Negative Keywords",
      },
      deniedDescription: "This negative keyword change was declined. Nothing was removed.",
      emptyLabel: "No Google Ads accounts removed negative keywords.",
      failedDescription: "The update did not finish. No negative keyword change was confirmed.",
      heading: "Remove Negative Keywords",
      malformedDescription:
        "The system couldn't verify this account's negative keyword outcomes. Check the Google Ads platform before taking further action.",
      parseResult: (value): NegativeKeywordRemovalResult | null =>
        listNegativeKeywordResult(value, true),
      progressLabel: "Removing Google Ads negative keywords…",
      renderOutcome: (result) => <NegativeKeywordRemovalOutcome result={result} />,
      resultAriaLabel: "Google Ads negative keyword results",
      resultFailure:
        "The system couldn't verify the negative keyword changes. Check the Google Ads platform before taking further action.",
      unconfirmedAriaLabel: "Unconfirmed Google Ads negative keyword update",
      unverifiedDescription:
        "The system couldn't verify whether Google Ads removed these negative keywords. Check the Google Ads platform before taking further action.",
      waitingLabel: "Waiting for negative keyword approval…",
    }),
  },
})
