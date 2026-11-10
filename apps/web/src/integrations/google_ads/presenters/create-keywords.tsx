// apps/web/src/integrations/google_ads/presenters/create-keywords.tsx

import { CreateKeywordsApproval } from "@/integrations/google_ads/components/create-keywords-approval"
import { CreateKeywordsOutcome } from "@/integrations/google_ads/components/create-keywords-outcome"
import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import {
  createKeywordsApproveLabel,
  createKeywordsBlock,
  createKeywordsDetails,
  createKeywordsPrompt,
  parseCreateKeywordsArgs,
  type CreateKeywordsArgs,
} from "@/integrations/google_ads/lib/create-keywords"
import {
  parseCreateKeywordsResult,
  type CreateKeywordsResult,
} from "@/integrations/google_ads/lib/create-keywords-result"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const googleAdsCreateKeywordsPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_create_keywords: defineIntegrationWriteVariant<
      CreateKeywordsArgs,
      CreateKeywordsResult
    >(googleAdsProvider, {
      copy: { verb: "Add", object: "keywords", effect: "added" },
      approval: {
        title: "Add Keywords",
        approveLabel: createKeywordsApproveLabel,
        parseArgs: parseCreateKeywordsArgs,
        prompt: createKeywordsPrompt,
        // An edit needs Google's answer, and problems follow what it last answered for.
        validateArgs: (value, checked) =>
          createKeywordsBlock(parseCreateKeywordsArgs(value), checked),
        renderInvalidDraft: true,
        renderFields: false,
        renderSummary: (value, fallback, onFieldEdit, disabled, controls) => (
          <CreateKeywordsApproval
            args={parseCreateKeywordsArgs(value) ?? fallback}
            checked={fallback}
            controls={controls}
            disabled={disabled}
            onFieldEdit={onFieldEdit}
          />
        ),
      },
      details: createKeywordsDetails,
      parseResult: parseCreateKeywordsResult,
      settledPartial: (result) => result.rows.some((row) => row.outcome === "failed"),
      settledUnverified: (result) => result.rows.some((row) => row.outcome === "unverified"),
      settledFailure: (result) =>
        result.rows.every((row) => row.outcome === "failed")
          ? "Google Ads didn't add any of these keywords."
          : null,
      renderFailure: (args, description, result) =>
        result ? (
          <div className="grid gap-3">
            <p className="text-destructive text-sm">{description}</p>
            <CreateKeywordsOutcome result={result} />
          </div>
        ) : (
          <GoogleAdsFailureTargets
            targets={args?.entries.map((entry) => entry.adGroup.label) ?? []}
            description={description}
          />
        ),
      renderOutcome: (result) => <CreateKeywordsOutcome result={result} />,
      renderUnverifiedOutcome: (result) => <CreateKeywordsOutcome result={result} />,
    }),
  },
})
