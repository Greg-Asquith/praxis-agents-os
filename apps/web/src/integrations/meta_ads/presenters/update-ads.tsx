// apps/web/src/integrations/meta_ads/presenters/update-ads.tsx

import { AdEditApproval, AdEditOutcome } from "@/integrations/meta_ads/components/ad-edits"
import { MetaAdsFailureTargets } from "@/integrations/meta_ads/components/outcome-table"
import {
  adEditDetails,
  adEditProblem,
  parseAdEditArgs,
  parseAdEditResult,
  type AdEditArgs,
  type AdEditResult,
} from "@/integrations/meta_ads/lib/ad-edits"
import { metaAdsProvider } from "@/integrations/meta_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const metaAdsUpdateAdsPresenter = createIntegrationWritePresenter({
  variants: {
    meta_ads_update_ads: defineIntegrationWriteVariant<AdEditArgs, AdEditResult>(metaAdsProvider, {
      copy: {
        verb: "Update",
        object: "ads",
        effect: "updated",
        check: "Check Ads Manager before taking further action.",
      },
      approval: {
        parseArgs: parseAdEditArgs,
        prompt: "Review each ad's new name or schedule before approving.",
        // A malformed value or a change Meta won't accept can't be approved.
        validateArgs: (value) => adEditProblem(parseAdEditArgs(value)),
        renderInvalidDraft: true,
        renderSummary: (value, fallback, onFieldEdit, disabled) => (
          <AdEditApproval
            args={parseAdEditArgs(value) ?? fallback}
            disabled={disabled}
            onFieldEdit={onFieldEdit}
            proposed={fallback}
          />
        ),
      },
      details: adEditDetails,
      parseResult: parseAdEditResult,
      settledPartial: (result) => result.ads.some((ad) => ad.outcome === "failed"),
      settledUnverified: (result) => result.ads.some((ad) => ad.outcome === "unverified"),
      settledFailure: (result) =>
        result.ads.every((ad) => ad.outcome === "failed")
          ? "Meta Ads didn't make any of these changes."
          : null,
      renderFailure: (args, description, result) =>
        result ? (
          <div className="grid gap-3">
            <p className="text-destructive text-sm">{description}</p>
            <AdEditOutcome result={result} />
          </div>
        ) : (
          <MetaAdsFailureTargets
            targets={args?.edits.map((edit) => edit.name) ?? []}
            description={description}
          />
        ),
      renderOutcome: (result) => <AdEditOutcome result={result} />,
      renderUnverifiedOutcome: (result) => <AdEditOutcome result={result} />,
    }),
  },
})
