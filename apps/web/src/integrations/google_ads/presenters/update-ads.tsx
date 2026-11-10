// apps/web/src/integrations/google_ads/presenters/update-ads.tsx

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import { UpdateAdsApproval } from "@/integrations/google_ads/components/update-ads-approval"
import { UpdateAdsOutcome } from "@/integrations/google_ads/components/update-ads-outcome"
import {
  parseUpdateAdsArgs,
  updateAdsApproveLabel,
  updateAdsBlock,
  updateAdsDetails,
  updateAdsPrompt,
  type UpdateAdsArgs,
} from "@/integrations/google_ads/lib/update-ads"
import {
  parseUpdateAdsResult,
  type UpdateAdsResult,
} from "@/integrations/google_ads/lib/update-ads-result"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const googleAdsUpdateAdsPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_update_ads: defineIntegrationWriteVariant<UpdateAdsArgs, UpdateAdsResult>(
      googleAdsProvider,
      {
        copy: { verb: "Update", object: "ads", effect: "updated" },
        approval: {
          title: "Change Ads",
          approveLabel: updateAdsApproveLabel,
          parseArgs: parseUpdateAdsArgs,
          prompt: updateAdsPrompt,
          // An edit needs Google's answer, and problems follow what it last answered for.
          validateArgs: (value, checked) => updateAdsBlock(parseUpdateAdsArgs(value), checked),
          renderInvalidDraft: true,
          renderFields: false,
          renderSummary: (value, fallback, onFieldEdit, disabled, controls) => (
            <UpdateAdsApproval
              args={parseUpdateAdsArgs(value) ?? fallback}
              checked={fallback}
              controls={controls}
              disabled={disabled}
              onFieldEdit={onFieldEdit}
            />
          ),
        },
        details: updateAdsDetails,
        parseResult: parseUpdateAdsResult,
        settledPartial: (result) => result.rows.some((row) => row.outcome === "failed"),
        settledUnverified: (result) => result.rows.some((row) => row.outcome === "unverified"),
        settledFailure: (result) =>
          result.rows.every((row) => row.outcome === "failed")
            ? "Google Ads didn't change any of these ads."
            : null,
        renderFailure: (args, description, result) =>
          result ? (
            <div className="grid gap-3">
              <p className="text-destructive text-sm">{description}</p>
              <UpdateAdsOutcome result={result} />
            </div>
          ) : (
            <GoogleAdsFailureTargets
              targets={args?.changes.map((change) => change.label) ?? []}
              description={description}
            />
          ),
        renderOutcome: (result) => <UpdateAdsOutcome result={result} />,
        renderUnverifiedOutcome: (result) => <UpdateAdsOutcome result={result} />,
      }
    ),
  },
})
