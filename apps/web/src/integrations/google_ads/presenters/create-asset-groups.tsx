// apps/web/src/integrations/google_ads/presenters/create-asset-groups.tsx

import { CampaignBuildOutcome } from "@/integrations/google_ads/components/campaign-build-outcome"
import { CreateAssetGroupsApproval } from "@/integrations/google_ads/components/create-asset-groups-approval"
import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import {
  hasFailures,
  hasUnverified,
  nothingCreated,
  parseCampaignBuildResult,
  type CampaignBuildResult,
} from "@/integrations/google_ads/lib/campaign-build-result"
import {
  createAssetGroupsApproveLabel,
  createAssetGroupsBlock,
  createAssetGroupsDetails,
  createAssetGroupsPrompt,
  parseCreateAssetGroupsArgs,
  type CreateAssetGroupsArgs,
} from "@/integrations/google_ads/lib/create-asset-groups"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

const EXPORT_NAME = "google-ads-added-asset-groups"

export const googleAdsCreateAssetGroupsPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_create_asset_groups: defineIntegrationWriteVariant<
      CreateAssetGroupsArgs,
      CampaignBuildResult
    >(googleAdsProvider, {
      copy: { verb: "Add", object: "asset groups", effect: "added" },
      approval: {
        title: "Add Asset Groups",
        approveLabel: createAssetGroupsApproveLabel,
        parseArgs: parseCreateAssetGroupsArgs,
        prompt: createAssetGroupsPrompt,
        // Problems follow the edited groups, and an edit needs Google's answer.
        validateArgs: (value, checked) =>
          createAssetGroupsBlock(parseCreateAssetGroupsArgs(value), checked),
        renderInvalidDraft: true,
        renderFields: false,
        renderSummary: (value, fallback, onFieldEdit, disabled, controls) => (
          <CreateAssetGroupsApproval
            args={parseCreateAssetGroupsArgs(value) ?? fallback}
            checked={fallback}
            controls={controls}
            disabled={disabled}
            onFieldEdit={onFieldEdit}
          />
        ),
      },
      details: createAssetGroupsDetails,
      parseResult: parseCampaignBuildResult,
      settledPartial: (result) => hasFailures(result) && !nothingCreated(result),
      settledUnverified: hasUnverified,
      settledFailure: (result) =>
        nothingCreated(result) ? "Google Ads didn't add any of these asset groups." : null,
      renderFailure: (args, description, result) =>
        result ? (
          <CampaignBuildOutcome exportName={EXPORT_NAME} result={result} />
        ) : (
          <GoogleAdsFailureTargets
            targets={args?.assetGroups.map((group) => group.name) ?? []}
            description={description}
          />
        ),
      renderOutcome: (result) => <CampaignBuildOutcome exportName={EXPORT_NAME} result={result} />,
      renderUnverifiedOutcome: (result) => (
        <CampaignBuildOutcome exportName={EXPORT_NAME} result={result} />
      ),
    }),
  },
})
