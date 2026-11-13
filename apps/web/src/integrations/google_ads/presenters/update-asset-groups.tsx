// apps/web/src/integrations/google_ads/presenters/update-asset-groups.tsx

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import { UpdateAssetGroupsApproval } from "@/integrations/google_ads/components/update-asset-groups-approval"
import { UpdateAssetGroupsOutcome } from "@/integrations/google_ads/components/update-asset-groups-outcome"
import {
  assetGroupsApproveLabel,
  assetGroupsBlock,
  assetGroupsDetails,
  assetGroupsPrompt,
  parseUpdateAssetGroupsArgs,
  type UpdateAssetGroupsArgs,
} from "@/integrations/google_ads/lib/update-asset-groups"
import {
  parseUpdateAssetGroupsResult,
  type UpdateAssetGroupsResult,
} from "@/integrations/google_ads/lib/update-asset-groups-result"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const googleAdsUpdateAssetGroupsPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_update_asset_groups: defineIntegrationWriteVariant<
      UpdateAssetGroupsArgs,
      UpdateAssetGroupsResult
    >(googleAdsProvider, {
      copy: { verb: "Update", object: "asset groups", effect: "updated" },
      approval: {
        title: "Change Asset Groups",
        approveLabel: assetGroupsApproveLabel,
        parseArgs: parseUpdateAssetGroupsArgs,
        prompt: assetGroupsPrompt,
        // An edit needs Google's answer, and problems follow what it last answered for.
        validateArgs: (value, checked) =>
          assetGroupsBlock(parseUpdateAssetGroupsArgs(value), checked),
        renderInvalidDraft: true,
        renderFields: false,
        renderSummary: (value, fallback, onFieldEdit, disabled, controls) => (
          <UpdateAssetGroupsApproval
            args={parseUpdateAssetGroupsArgs(value) ?? fallback}
            checked={fallback}
            controls={controls}
            disabled={disabled}
            onFieldEdit={onFieldEdit}
          />
        ),
      },
      details: assetGroupsDetails,
      parseResult: parseUpdateAssetGroupsResult,
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
            <UpdateAssetGroupsOutcome result={result} />
          </div>
        ) : (
          <GoogleAdsFailureTargets
            targets={args?.entries.map((entry) => entry.label) ?? []}
            description={description}
          />
        ),
      renderOutcome: (result) => <UpdateAssetGroupsOutcome result={result} />,
      renderUnverifiedOutcome: (result) => <UpdateAssetGroupsOutcome result={result} />,
    }),
  },
})
