// apps/web/src/integrations/meta_ads/presenters/update-campaigns.tsx

import {
  CampaignEditApproval,
  CampaignEditOutcome,
} from "@/integrations/meta_ads/components/campaign-edits"
import { MetaAdsFailureTargets } from "@/integrations/meta_ads/components/outcome-table"
import {
  campaignEditDetails,
  campaignEditProblem,
  parseCampaignEditArgs,
  parseCampaignEditResult,
  type CampaignEditArgs,
  type CampaignEditResult,
} from "@/integrations/meta_ads/lib/campaign-edits"
import { metaAdsProvider } from "@/integrations/meta_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const metaAdsUpdateCampaignsPresenter = createIntegrationWritePresenter({
  variants: {
    meta_ads_update_campaigns: defineIntegrationWriteVariant<CampaignEditArgs, CampaignEditResult>(
      metaAdsProvider,
      {
        copy: {
          verb: "Update",
          object: "campaigns",
          effect: "updated",
          check: "Check Ads Manager before taking further action.",
        },
        approval: {
          parseArgs: parseCampaignEditArgs,
          prompt: "Review each setting before changing how these campaigns spend and bid.",
          // A malformed value or a change Meta won't accept can't be approved.
          validateArgs: (value) => campaignEditProblem(parseCampaignEditArgs(value)),
          renderInvalidDraft: true,
          renderSummary: (value, fallback, onFieldEdit, disabled) => (
            <CampaignEditApproval
              args={parseCampaignEditArgs(value) ?? fallback}
              disabled={disabled}
              onFieldEdit={onFieldEdit}
              proposed={fallback}
            />
          ),
        },
        details: campaignEditDetails,
        parseResult: parseCampaignEditResult,
        settledPartial: (result) => result.campaigns.some((item) => item.outcome === "failed"),
        settledUnverified: (result) =>
          result.campaigns.some((item) => item.outcome === "unverified"),
        settledFailure: (result) =>
          result.campaigns.every((item) => item.outcome === "failed")
            ? "Meta Ads didn't make any of these changes."
            : null,
        renderFailure: (args, description, result) =>
          result ? (
            <div className="grid gap-3">
              <p className="text-destructive text-sm">{description}</p>
              <CampaignEditOutcome result={result} />
            </div>
          ) : (
            <MetaAdsFailureTargets
              targets={args?.edits.map((edit) => edit.name) ?? []}
              description={description}
            />
          ),
        renderOutcome: (result) => <CampaignEditOutcome result={result} />,
        renderUnverifiedOutcome: (result) => <CampaignEditOutcome result={result} />,
      }
    ),
  },
})
