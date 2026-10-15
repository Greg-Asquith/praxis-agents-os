// apps/web/src/integrations/meta_ads/presenters/create-campaign.tsx

import {
  CreateCampaignApproval,
  CreateCampaignOutcome,
} from "@/integrations/meta_ads/components/campaign-summary"
import { MetaAdsFailureTargets } from "@/integrations/meta_ads/components/outcome-table"
import {
  campaignPrompt,
  createCampaignProblem,
  parseCreateCampaignArgs,
  parseCreateCampaignResult,
  type CreateCampaignArgs,
  type CreateCampaignResult,
} from "@/integrations/meta_ads/lib/create-campaign"
import { metaAdsProvider } from "@/integrations/meta_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const metaAdsCreateCampaignPresenter = createIntegrationWritePresenter({
  variants: {
    meta_ads_create_campaign: defineIntegrationWriteVariant<
      CreateCampaignArgs,
      CreateCampaignResult
    >(metaAdsProvider, {
      copy: {
        verb: "Create",
        object: "campaign",
        effect: "created",
        check: "Check Ads Manager before creating this campaign again.",
      },
      approval: {
        parseArgs: parseCreateCampaignArgs,
        prompt: campaignPrompt,
        validateArgs: (value) => createCampaignProblem(parseCreateCampaignArgs(value)),
        renderInvalidDraft: true,
        renderSummary: (value, fallback, onFieldEdit, disabled) => (
          <CreateCampaignApproval
            args={parseCreateCampaignArgs(value) ?? fallback}
            disabled={disabled}
            onFieldEdit={onFieldEdit}
          />
        ),
      },
      details: (args) => (args ? [{ label: "Campaign", value: args.name }] : []),
      parseResult: parseCreateCampaignResult,
      settledUnverified: (result) => result.campaign.outcome === "unverified",
      settledFailure: (result) =>
        result.campaign.outcome === "failed" ? "Meta Ads didn't create this campaign." : null,
      renderFailure: (args, description, result) =>
        result ? (
          <div className="grid gap-3">
            <p className="text-destructive text-sm">{description}</p>
            <CreateCampaignOutcome result={result} />
          </div>
        ) : (
          <MetaAdsFailureTargets description={description} targets={args ? [args.name] : []} />
        ),
      renderOutcome: (result) => <CreateCampaignOutcome result={result} />,
      renderUnverifiedOutcome: (result) => <CreateCampaignOutcome result={result} />,
    }),
  },
})
