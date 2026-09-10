// apps/web/src/integrations/google_ads/presenters/negative-keywords/list.tsx

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"

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
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const googleAdsListNegativeKeywordsPresenter = createIntegrationWritePresenter({
  key: "google-ads-list-negative-keywords",
  variants: {
    google_ads_add_negative_keywords: defineIntegrationWriteVariant(googleAdsProvider, {
      copy: { verb: "Add", object: "negative keywords", effect: "added" },
      approval: {
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
      },
      parseResult: (value): NegativeKeywordResult | null => listNegativeKeywordResult(value, false),
      renderFailure: (args, description) => (
        <GoogleAdsFailureTargets description={description} targets={args ? [args.listName] : []} />
      ),
      renderOutcome: (result) => <NegativeKeywordOutcome result={result} />,
    }),
    google_ads_remove_negative_keywords: defineIntegrationWriteVariant(googleAdsProvider, {
      copy: { verb: "Remove", object: "negative keywords", effect: "removed" },
      approval: {
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
      },
      parseResult: (value): NegativeKeywordRemovalResult | null =>
        listNegativeKeywordResult(value, true),
      renderFailure: (args, description) => (
        <GoogleAdsFailureTargets description={description} targets={args ? [args.listName] : []} />
      ),
      renderOutcome: (result) => <NegativeKeywordRemovalOutcome result={result} />,
    }),
  },
})
