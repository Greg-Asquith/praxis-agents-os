// apps/web/src/integrations/google_ads/presenters/update-campaigns.tsx

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import { UpdateCampaignsApproval } from "@/integrations/google_ads/components/update-campaigns-approval"
import { UpdateCampaignsOutcome } from "@/integrations/google_ads/components/update-campaigns-outcome"
import {
  campaignsApproveLabel,
  campaignsBlock,
  campaignsDetails,
  campaignsPrompt,
  parseUpdateCampaignsArgs,
  type UpdateCampaignsArgs,
} from "@/integrations/google_ads/lib/update-campaigns"
import {
  parseUpdateCampaignsResult,
  type UpdateCampaignsResult,
} from "@/integrations/google_ads/lib/update-campaigns-result"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const googleAdsUpdateCampaignsPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_update_campaigns: defineIntegrationWriteVariant<
      UpdateCampaignsArgs,
      UpdateCampaignsResult
    >(googleAdsProvider, {
      copy: { verb: "Update", object: "campaigns", effect: "updated" },
      approval: {
        title: "Change Campaign Settings",
        approveLabel: campaignsApproveLabel,
        parseArgs: parseUpdateCampaignsArgs,
        prompt: campaignsPrompt,
        // An edit needs Google's answer, and problems follow what it last answered for.
        validateArgs: (value, checked) => campaignsBlock(parseUpdateCampaignsArgs(value), checked),
        renderInvalidDraft: true,
        renderFields: false,
        renderSummary: (value, fallback, onFieldEdit, disabled, controls) => (
          <UpdateCampaignsApproval
            args={parseUpdateCampaignsArgs(value) ?? fallback}
            checked={fallback}
            controls={controls}
            disabled={disabled}
            onFieldEdit={onFieldEdit}
          />
        ),
      },
      details: campaignsDetails,
      parseResult: parseUpdateCampaignsResult,
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
            <UpdateCampaignsOutcome result={result} />
          </div>
        ) : (
          <GoogleAdsFailureTargets
            targets={args?.changes.map((change) => change.label) ?? []}
            description={description}
          />
        ),
      renderOutcome: (result) => <UpdateCampaignsOutcome result={result} />,
      renderUnverifiedOutcome: (result) => <UpdateCampaignsOutcome result={result} />,
    }),
  },
})
