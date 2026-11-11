// apps/web/src/integrations/google_ads/presenters/update-assets.tsx

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import { UpdateAssetsApproval } from "@/integrations/google_ads/components/update-assets-approval"
import { UpdateAssetsOutcome } from "@/integrations/google_ads/components/update-assets-outcome"
import {
  assetsApproveLabel,
  assetsBlock,
  assetsDetails,
  assetsPrompt,
  parseUpdateAssetsArgs,
  type UpdateAssetsArgs,
} from "@/integrations/google_ads/lib/update-assets"
import {
  parseUpdateAssetsResult,
  type UpdateAssetsResult,
} from "@/integrations/google_ads/lib/update-assets-result"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const googleAdsUpdateAssetsPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_update_assets: defineIntegrationWriteVariant<UpdateAssetsArgs, UpdateAssetsResult>(
      googleAdsProvider,
      {
        copy: { verb: "Update", object: "ad assets", effect: "updated" },
        approval: {
          title: "Update Ad Assets",
          approveLabel: assetsApproveLabel,
          parseArgs: parseUpdateAssetsArgs,
          prompt: assetsPrompt,
          // An edit needs Google's answer, and problems follow what it last answered for.
          validateArgs: (value, checked) => assetsBlock(parseUpdateAssetsArgs(value), checked),
          renderInvalidDraft: true,
          renderFields: false,
          renderSummary: (value, fallback, onFieldEdit, disabled, controls) => (
            <UpdateAssetsApproval
              args={parseUpdateAssetsArgs(value) ?? fallback}
              checked={fallback}
              controls={controls}
              disabled={disabled}
              onFieldEdit={onFieldEdit}
            />
          ),
        },
        details: assetsDetails,
        parseResult: parseUpdateAssetsResult,
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
              <UpdateAssetsOutcome result={result} />
            </div>
          ) : (
            <GoogleAdsFailureTargets
              targets={[
                ...(args?.entries.map((entry) => entry.label) ?? []),
                ...(args?.changes.map((change) => change.ref.label) ?? []),
              ]}
              description={description}
            />
          ),
        renderOutcome: (result) => <UpdateAssetsOutcome result={result} />,
        renderUnverifiedOutcome: (result) => <UpdateAssetsOutcome result={result} />,
      }
    ),
  },
})
