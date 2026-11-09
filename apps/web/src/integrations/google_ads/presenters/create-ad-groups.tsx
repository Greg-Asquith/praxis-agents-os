// apps/web/src/integrations/google_ads/presenters/create-ad-groups.tsx

import { CreateAdGroupsApproval } from "@/integrations/google_ads/components/create-ad-groups-approval"
import { CampaignBuildOutcome } from "@/integrations/google_ads/components/campaign-build-outcome"
import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import {
  createAdGroupsApproveLabel,
  createAdGroupsBlock,
  createAdGroupsDetails,
  createAdGroupsPrompt,
  parseCreateAdGroupsArgs,
  type CreateAdGroupsArgs,
} from "@/integrations/google_ads/lib/create-ad-groups"
import {
  hasFailures,
  hasUnverified,
  nothingCreated,
  parseCampaignBuildResult,
  type CampaignBuildResult,
} from "@/integrations/google_ads/lib/campaign-build-result"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const googleAdsCreateAdGroupsPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_create_ad_groups: defineIntegrationWriteVariant<
      CreateAdGroupsArgs,
      CampaignBuildResult
    >(googleAdsProvider, {
      copy: { verb: "Create", object: "ad groups", effect: "created" },
      approval: {
        title: "Create Ad Groups",
        approveLabel: createAdGroupsApproveLabel,
        parseArgs: parseCreateAdGroupsArgs,
        prompt: createAdGroupsPrompt,
        // Problems follow the edited names and bids, and an edit needs Google's answer.
        validateArgs: (value, checked) =>
          createAdGroupsBlock(parseCreateAdGroupsArgs(value), checked),
        renderInvalidDraft: true,
        renderFields: false,
        renderSummary: (value, fallback, onFieldEdit, disabled, controls) => (
          <CreateAdGroupsApproval
            args={parseCreateAdGroupsArgs(value) ?? fallback}
            checked={fallback}
            controls={controls}
            disabled={disabled}
            onFieldEdit={onFieldEdit}
          />
        ),
      },
      details: createAdGroupsDetails,
      parseResult: parseCampaignBuildResult,
      settledPartial: (result) => hasFailures(result) && !nothingCreated(result),
      settledUnverified: hasUnverified,
      settledFailure: (result) =>
        nothingCreated(result) ? "Google Ads didn't create any of these ad groups." : null,
      renderFailure: (args, description, result) =>
        result ? (
          <CampaignBuildOutcome exportName="google-ads-created-ad-groups" result={result} />
        ) : (
          <GoogleAdsFailureTargets
            targets={args?.adGroups.map((group) => group.name) ?? []}
            description={description}
          />
        ),
      renderOutcome: (result) => (
        <CampaignBuildOutcome exportName="google-ads-created-ad-groups" result={result} />
      ),
      renderUnverifiedOutcome: (result) => (
        <CampaignBuildOutcome exportName="google-ads-created-ad-groups" result={result} />
      ),
    }),
  },
})
