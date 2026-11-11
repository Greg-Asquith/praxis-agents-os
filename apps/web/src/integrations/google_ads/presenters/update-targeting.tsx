// apps/web/src/integrations/google_ads/presenters/update-targeting.tsx

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import { TargetingApproval } from "@/integrations/google_ads/components/targeting-approval"
import { TargetingOutcomeTable } from "@/integrations/google_ads/components/targeting-outcome"
import {
  parseUpdateTargetingArgs,
  targetingApproveLabel,
  targetingBlock,
  targetingDetails,
  targetingPrompt,
  type UpdateTargetingArgs,
} from "@/integrations/google_ads/lib/update-targeting"
import {
  parseUpdateTargetingResult,
  type UpdateTargetingResult,
} from "@/integrations/google_ads/lib/update-targeting-result"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const googleAdsUpdateTargetingPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_update_targeting: defineIntegrationWriteVariant<
      UpdateTargetingArgs,
      UpdateTargetingResult
    >(googleAdsProvider, {
      copy: { verb: "Update", object: "targeting", effect: "updated" },
      approval: {
        title: "Change Who Campaigns Reach",
        approveLabel: targetingApproveLabel,
        parseArgs: parseUpdateTargetingArgs,
        prompt: targetingPrompt,
        // An edit needs Google's answer, and problems follow what it last answered for.
        validateArgs: (value, checked) => targetingBlock(parseUpdateTargetingArgs(value), checked),
        renderInvalidDraft: true,
        renderFields: false,
        renderSummary: (value, fallback, onFieldEdit, disabled, controls) => (
          <TargetingApproval
            args={parseUpdateTargetingArgs(value) ?? fallback}
            checked={fallback}
            controls={controls}
            disabled={disabled}
            onFieldEdit={onFieldEdit}
          />
        ),
      },
      details: targetingDetails,
      parseResult: parseUpdateTargetingResult,
      settledPartial: (result) => result.rows.some((row) => row.outcome === "failed"),
      settledUnverified: (result) => result.rows.some((row) => row.outcome === "unverified"),
      settledFailure: (result) =>
        result.rows.length > 0 && result.rows.every((row) => row.outcome === "failed")
          ? "Google Ads didn't make any of these changes."
          : null,
      renderFailure: (args, description, result) =>
        result ? (
          <div className="grid gap-3">
            <p className="text-destructive text-sm">{description}</p>
            <TargetingOutcomeTable result={result} />
          </div>
        ) : (
          <GoogleAdsFailureTargets
            targets={args?.changes.map((change) => change.label) ?? []}
            description={description}
          />
        ),
      renderOutcome: (result) => <TargetingOutcomeTable result={result} />,
      renderUnverifiedOutcome: (result) => <TargetingOutcomeTable result={result} />,
    }),
  },
})
