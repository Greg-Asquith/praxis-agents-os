// apps/web/src/integrations/meta_ads/presenters/create-campaign.tsx

import { CreateCampaignApproval } from "@/integrations/meta_ads/components/campaign-summary"
import { CreatedObjectOutcome } from "@/integrations/meta_ads/components/create-summary"
import { MetaAdsFailureTargets } from "@/integrations/meta_ads/components/outcome-table"
import {
  campaignPrompt,
  createCampaignProblem,
  parseCreateCampaignArgs,
  type CreateCampaignArgs,
} from "@/integrations/meta_ads/lib/create-campaign"
import {
  editFields,
  parseCreatedObject,
  type CreatedObjectResult,
} from "@/integrations/meta_ads/lib/create-summary"
import { metaAdsProvider } from "@/integrations/meta_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const metaAdsCreateCampaignPresenter = createIntegrationWritePresenter({
  variants: {
    meta_ads_create_campaign: defineIntegrationWriteVariant<
      CreateCampaignArgs,
      CreatedObjectResult
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
        renderFields: false,
        renderSummary: (value, fallback, _onFieldEdit, disabled, controls) => (
          <CreateCampaignApproval
            args={parseCreateCampaignArgs(value) ?? fallback}
            disabled={disabled}
            onEdit={(edits) => {
              editFields(controls, disabled, edits)
            }}
          />
        ),
      },
      details: (args) => (args ? [{ label: "Campaign", value: args.name }] : []),
      parseResult: (value) => parseCreatedObject(value, "campaign", "campaign_id"),
      settledUnverified: (result) => result.outcome === "unverified",
      settledFailure: (result) =>
        result.outcome === "failed" ? "Meta Ads didn't create this campaign." : null,
      renderFailure: (args, description, result) =>
        result ? (
          <div className="grid gap-3">
            <p className="text-destructive text-sm">{description}</p>
            <CreatedObjectOutcome result={result} type="campaign" />
          </div>
        ) : (
          <MetaAdsFailureTargets description={description} targets={args ? [args.name] : []} />
        ),
      renderOutcome: (result) => <CreatedObjectOutcome result={result} type="campaign" />,
      renderUnverifiedOutcome: (result) => <CreatedObjectOutcome result={result} type="campaign" />,
    }),
  },
})
