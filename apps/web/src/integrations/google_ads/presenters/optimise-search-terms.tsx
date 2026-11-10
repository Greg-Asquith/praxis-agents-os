// apps/web/src/integrations/google_ads/presenters/optimise-search-terms.tsx

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import { SearchTermsApproval } from "@/integrations/google_ads/components/search-terms-approval"
import { SearchTermsOutcome } from "@/integrations/google_ads/components/search-terms-outcome"
import {
  parseSearchTermsArgs,
  searchTermsApproveLabel,
  searchTermsBlock,
  searchTermsDetails,
  searchTermsPrompt,
  type OptimiseSearchTermsArgs,
} from "@/integrations/google_ads/lib/search-terms"
import {
  parseSearchTermsResult,
  type OptimiseSearchTermsResult,
} from "@/integrations/google_ads/lib/search-terms-result"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const googleAdsOptimiseSearchTermsPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_optimise_search_terms: defineIntegrationWriteVariant<
      OptimiseSearchTermsArgs,
      OptimiseSearchTermsResult
    >(googleAdsProvider, {
      copy: { verb: "Optimise", object: "search terms", effect: "optimised" },
      approval: {
        title: "Optimise Search Terms",
        approveLabel: searchTermsApproveLabel,
        parseArgs: parseSearchTermsArgs,
        prompt: searchTermsPrompt,
        // An edit needs Google's answer, and problems follow what it last answered for.
        validateArgs: (value, checked) => searchTermsBlock(parseSearchTermsArgs(value), checked),
        renderInvalidDraft: true,
        renderFields: false,
        renderSummary: (value, fallback, onFieldEdit, disabled, controls) => (
          <SearchTermsApproval
            args={parseSearchTermsArgs(value) ?? fallback}
            checked={fallback}
            controls={controls}
            disabled={disabled}
            onFieldEdit={onFieldEdit}
          />
        ),
      },
      details: searchTermsDetails,
      parseResult: parseSearchTermsResult,
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
            <SearchTermsOutcome result={result} />
          </div>
        ) : (
          <GoogleAdsFailureTargets
            targets={args?.decisions.map((decision) => decision.term) ?? []}
            description={description}
          />
        ),
      renderOutcome: (result) => <SearchTermsOutcome result={result} />,
      renderUnverifiedOutcome: (result) => <SearchTermsOutcome result={result} />,
    }),
  },
})
