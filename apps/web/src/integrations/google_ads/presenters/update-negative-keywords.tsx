// apps/web/src/integrations/google_ads/presenters/update-negative-keywords.tsx

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import { NegativeKeywordsApproval } from "@/integrations/google_ads/components/negative-keywords-approval"
import { NegativeKeywordsOutcome } from "@/integrations/google_ads/components/negative-keywords-outcome"
import {
  negativeApproveLabel,
  negativeBlock,
  negativeDetails,
  negativePrompt,
  parseNegativeKeywordsArgs,
  type UpdateNegativeKeywordsArgs,
} from "@/integrations/google_ads/lib/negative-keywords"
import {
  parseNegativeKeywordsResult,
  type UpdateNegativeKeywordsResult,
} from "@/integrations/google_ads/lib/negative-keywords-result"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const googleAdsUpdateNegativeKeywordsPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_update_negative_keywords: defineIntegrationWriteVariant<
      UpdateNegativeKeywordsArgs,
      UpdateNegativeKeywordsResult
    >(googleAdsProvider, {
      copy: { verb: "Update", object: "negative keywords", effect: "updated" },
      approval: {
        title: "Update Negative Keywords",
        approveLabel: negativeApproveLabel,
        parseArgs: parseNegativeKeywordsArgs,
        prompt: negativePrompt,
        // An edit needs Google's answer, and problems follow what it last answered for.
        validateArgs: (value, checked) => negativeBlock(parseNegativeKeywordsArgs(value), checked),
        renderInvalidDraft: true,
        renderFields: false,
        renderSummary: (value, fallback, onFieldEdit, disabled, controls) => (
          <NegativeKeywordsApproval
            args={parseNegativeKeywordsArgs(value) ?? fallback}
            checked={fallback}
            controls={controls}
            disabled={disabled}
            onFieldEdit={onFieldEdit}
          />
        ),
      },
      details: negativeDetails,
      parseResult: parseNegativeKeywordsResult,
      settledPartial: (result) => result.rows.some((row) => row.outcome === "failed"),
      settledUnverified: (result) => result.rows.some((row) => row.outcome === "unverified"),
      settledFailure: (result) =>
        result.rows.every((row) => row.outcome === "failed")
          ? "Google Ads didn't make any of these changes."
          : null,
      renderFailure: (args, description, result) =>
        result ? (
          <div className="grid gap-3">
            <p className="text-destructive text-sm">{description}</p>
            <NegativeKeywordsOutcome result={result} />
          </div>
        ) : (
          <GoogleAdsFailureTargets
            targets={args?.entries.map((entry) => entry.label) ?? []}
            description={description}
          />
        ),
      renderOutcome: (result) => <NegativeKeywordsOutcome result={result} />,
      renderUnverifiedOutcome: (result) => <NegativeKeywordsOutcome result={result} />,
    }),
  },
})
