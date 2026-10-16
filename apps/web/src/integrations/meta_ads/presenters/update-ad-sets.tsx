// apps/web/src/integrations/meta_ads/presenters/update-ad-sets.tsx

import {
  AdSetEditApproval,
  AdSetEditOutcome,
} from "@/integrations/meta_ads/components/ad-set-edits"
import { MetaAdsFailureTargets } from "@/integrations/meta_ads/components/outcome-table"
import {
  adSetEditDetails,
  adSetEditProblem,
  parseAdSetEditArgs,
  parseAdSetEditResult,
  type AdSetEditArgs,
  type AdSetEditResult,
} from "@/integrations/meta_ads/lib/ad-set-edits"
import { metaAdsProvider } from "@/integrations/meta_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const metaAdsUpdateAdSetsPresenter = createIntegrationWritePresenter({
  variants: {
    meta_ads_update_ad_sets: defineIntegrationWriteVariant<AdSetEditArgs, AdSetEditResult>(
      metaAdsProvider,
      {
        copy: {
          verb: "Update",
          object: "ad sets",
          effect: "updated",
          check: "Check Ads Manager before taking further action.",
        },
        approval: {
          parseArgs: parseAdSetEditArgs,
          prompt: "Review each setting before changing how these ad sets deliver.",
          // A malformed value or a change Meta won't accept can't be approved.
          validateArgs: (value) => adSetEditProblem(parseAdSetEditArgs(value)),
          renderInvalidDraft: true,
          renderSummary: (value, fallback, onFieldEdit, disabled) => (
            <AdSetEditApproval
              args={parseAdSetEditArgs(value) ?? fallback}
              disabled={disabled}
              onFieldEdit={onFieldEdit}
              proposed={fallback}
            />
          ),
        },
        details: adSetEditDetails,
        parseResult: parseAdSetEditResult,
        settledPartial: (result) => result.adSets.some((adSet) => adSet.outcome === "failed"),
        settledUnverified: (result) =>
          result.adSets.some((adSet) => adSet.outcome === "unverified"),
        settledFailure: (result) =>
          result.adSets.every((adSet) => adSet.outcome === "failed")
            ? "Meta Ads didn't make any of these changes."
            : null,
        renderFailure: (args, description, result) =>
          result ? (
            <div className="grid gap-3">
              <p className="text-destructive text-sm">{description}</p>
              <AdSetEditOutcome result={result} />
            </div>
          ) : (
            <MetaAdsFailureTargets
              targets={args?.edits.map((edit) => edit.name) ?? []}
              description={description}
            />
          ),
        renderOutcome: (result) => <AdSetEditOutcome result={result} />,
        renderUnverifiedOutcome: (result) => <AdSetEditOutcome result={result} />,
      }
    ),
  },
})
