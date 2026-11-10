// apps/web/src/integrations/google_ads/presenters/update-keywords.tsx

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import { UpdateKeywordsApproval } from "@/integrations/google_ads/components/update-keywords-approval"
import { UpdateKeywordsOutcome } from "@/integrations/google_ads/components/update-keywords-outcome"
import {
  keywordsApproveLabel,
  keywordsBlock,
  keywordsDetails,
  keywordsPrompt,
  parseUpdateKeywordsArgs,
  type UpdateKeywordsArgs,
} from "@/integrations/google_ads/lib/update-keywords"
import {
  parseUpdateKeywordsResult,
  type UpdateKeywordsResult,
} from "@/integrations/google_ads/lib/update-keywords-result"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const googleAdsUpdateKeywordsPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_update_keywords: defineIntegrationWriteVariant<
      UpdateKeywordsArgs,
      UpdateKeywordsResult
    >(googleAdsProvider, {
      copy: { verb: "Update", object: "keywords", effect: "updated" },
      approval: {
        title: "Update Keywords",
        approveLabel: keywordsApproveLabel,
        parseArgs: parseUpdateKeywordsArgs,
        prompt: keywordsPrompt,
        // An edit needs Google's answer, and problems follow what it last answered for.
        validateArgs: (value, checked) => keywordsBlock(parseUpdateKeywordsArgs(value), checked),
        renderInvalidDraft: true,
        renderFields: false,
        renderSummary: (value, fallback, onFieldEdit, disabled, controls) => (
          <UpdateKeywordsApproval
            args={parseUpdateKeywordsArgs(value) ?? fallback}
            checked={fallback}
            controls={controls}
            disabled={disabled}
            onFieldEdit={onFieldEdit}
          />
        ),
      },
      details: keywordsDetails,
      parseResult: parseUpdateKeywordsResult,
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
            <UpdateKeywordsOutcome result={result} />
          </div>
        ) : (
          <GoogleAdsFailureTargets
            targets={args?.changes.map((change) => change.label) ?? []}
            description={description}
          />
        ),
      renderOutcome: (result) => <UpdateKeywordsOutcome result={result} />,
      renderUnverifiedOutcome: (result) => <UpdateKeywordsOutcome result={result} />,
    }),
  },
})
