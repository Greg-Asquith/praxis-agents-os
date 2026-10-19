// apps/web/src/integrations/meta_ads/presenters/update-targeting.tsx

import { MetaAdsFailureTargets } from "@/integrations/meta_ads/components/outcome-table"
import {
  TargetingEditApproval,
  TargetingEditOutcome,
} from "@/integrations/meta_ads/components/targeting-edits"
import {
  parseTargetingEditArgs,
  parseTargetingEditResult,
  targetingEditDetails,
  targetingEditProblem,
  type TargetingEditArgs,
  type TargetingEditResult,
} from "@/integrations/meta_ads/lib/targeting-edits"
import { metaAdsProvider } from "@/integrations/meta_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const metaAdsUpdateTargetingPresenter = createIntegrationWritePresenter({
  variants: {
    meta_ads_update_targeting: defineIntegrationWriteVariant<
      TargetingEditArgs,
      TargetingEditResult
    >(metaAdsProvider, {
      copy: {
        verb: "Update",
        object: "ad set targeting",
        effect: "updated",
        check: "Check Ads Manager before taking further action.",
      },
      approval: {
        parseArgs: parseTargetingEditArgs,
        prompt: "Review who each ad set reaches before and after the change.",
        // An emptied entry or a change Meta won't accept can't be approved.
        validateArgs: (value) => targetingEditProblem(parseTargetingEditArgs(value)),
        renderInvalidDraft: true,
        renderSummary: (value, fallback, onFieldEdit, disabled) => (
          <TargetingEditApproval
            args={parseTargetingEditArgs(value) ?? fallback}
            disabled={disabled}
            onFieldEdit={onFieldEdit}
            proposed={fallback}
          />
        ),
      },
      details: targetingEditDetails,
      parseResult: parseTargetingEditResult,
      settledPartial: (result) => result.adSets.some((adSet) => adSet.outcome === "failed"),
      settledUnverified: (result) => result.adSets.some((adSet) => adSet.outcome === "unverified"),
      settledFailure: (result) =>
        result.adSets.every((adSet) => adSet.outcome === "failed")
          ? "Meta Ads didn't make any of these changes."
          : null,
      renderFailure: (args, description, result) =>
        result ? (
          <div className="grid gap-3">
            <p className="text-destructive text-sm">{description}</p>
            <TargetingEditOutcome result={result} />
          </div>
        ) : (
          <MetaAdsFailureTargets
            targets={args?.edits.map((edit) => edit.name) ?? []}
            description={description}
          />
        ),
      renderOutcome: (result) => <TargetingEditOutcome result={result} />,
      renderUnverifiedOutcome: (result) => <TargetingEditOutcome result={result} />,
    }),
  },
})
