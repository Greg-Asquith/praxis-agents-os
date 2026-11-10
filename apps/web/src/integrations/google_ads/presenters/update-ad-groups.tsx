// apps/web/src/integrations/google_ads/presenters/update-ad-groups.tsx

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import { UpdateAdGroupsApproval } from "@/integrations/google_ads/components/update-ad-groups-approval"
import { UpdateAdGroupsOutcome } from "@/integrations/google_ads/components/update-ad-groups-outcome"
import {
  adGroupsApproveLabel,
  adGroupsBlock,
  adGroupsDetails,
  adGroupsPrompt,
  parseUpdateAdGroupsArgs,
  type UpdateAdGroupsArgs,
} from "@/integrations/google_ads/lib/update-ad-groups"
import {
  parseUpdateAdGroupsResult,
  type UpdateAdGroupsResult,
} from "@/integrations/google_ads/lib/update-ad-groups-result"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const googleAdsUpdateAdGroupsPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_update_ad_groups: defineIntegrationWriteVariant<
      UpdateAdGroupsArgs,
      UpdateAdGroupsResult
    >(googleAdsProvider, {
      copy: { verb: "Update", object: "ad groups", effect: "updated" },
      approval: {
        title: "Change Ad Group Settings",
        approveLabel: adGroupsApproveLabel,
        parseArgs: parseUpdateAdGroupsArgs,
        prompt: adGroupsPrompt,
        // An edit needs Google's answer, and problems follow what it last answered for.
        validateArgs: (value, checked) => adGroupsBlock(parseUpdateAdGroupsArgs(value), checked),
        renderInvalidDraft: true,
        renderFields: false,
        renderSummary: (value, fallback, onFieldEdit, disabled, controls) => (
          <UpdateAdGroupsApproval
            args={parseUpdateAdGroupsArgs(value) ?? fallback}
            checked={fallback}
            controls={controls}
            disabled={disabled}
            onFieldEdit={onFieldEdit}
          />
        ),
      },
      details: adGroupsDetails,
      parseResult: parseUpdateAdGroupsResult,
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
            <UpdateAdGroupsOutcome result={result} />
          </div>
        ) : (
          <GoogleAdsFailureTargets
            targets={args?.changes.map((change) => change.label) ?? []}
            description={description}
          />
        ),
      renderOutcome: (result) => <UpdateAdGroupsOutcome result={result} />,
      renderUnverifiedOutcome: (result) => <UpdateAdGroupsOutcome result={result} />,
    }),
  },
})
