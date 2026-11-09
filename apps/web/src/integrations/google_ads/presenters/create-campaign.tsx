// apps/web/src/integrations/google_ads/presenters/create-campaign.tsx

import { CampaignBuildOutcome } from "@/integrations/google_ads/components/campaign-build-outcome"
import { CreateCampaignApproval } from "@/integrations/google_ads/components/create-campaign-approval"
import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import {
  hasFailures,
  hasUnverified,
  nothingCreated,
  parseCampaignBuildResult,
  type CampaignBuildResult,
} from "@/integrations/google_ads/lib/campaign-build-result"
import {
  createCampaignBlock,
  createCampaignDetails,
  createCampaignPrompt,
  parseCreateCampaignArgs,
  type CreateCampaignArgs,
} from "@/integrations/google_ads/lib/create-campaign"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

const EXPORT_NAME = "google-ads-created-campaign"

export const googleAdsCreateCampaignPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_create_campaign: defineIntegrationWriteVariant<
      CreateCampaignArgs,
      CampaignBuildResult
    >(googleAdsProvider, {
      copy: { verb: "Create", object: "campaign", effect: "created" },
      approval: {
        title: "Create Search Campaign",
        approveLabel: "Create Campaign",
        parseArgs: parseCreateCampaignArgs,
        prompt: createCampaignPrompt,
        // Problems follow the edited settings, and an edit needs Google's answer.
        validateArgs: (value, checked) =>
          createCampaignBlock(parseCreateCampaignArgs(value), checked),
        renderInvalidDraft: true,
        renderFields: false,
        renderSummary: (value, fallback, onFieldEdit, disabled, controls) => (
          <CreateCampaignApproval
            args={parseCreateCampaignArgs(value) ?? fallback}
            checked={fallback}
            controls={controls}
            disabled={disabled}
            onFieldEdit={onFieldEdit}
          />
        ),
      },
      details: createCampaignDetails,
      parseResult: parseCampaignBuildResult,
      settledPartial: (result) => hasFailures(result) && !nothingCreated(result),
      settledUnverified: hasUnverified,
      settledFailure: (result) =>
        nothingCreated(result) ? "Google Ads didn't create this campaign." : null,
      renderFailure: (args, description, result) =>
        result ? (
          <CampaignBuildOutcome exportName={EXPORT_NAME} result={result} />
        ) : (
          <GoogleAdsFailureTargets
            targets={args ? [args.campaign.name] : []}
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
