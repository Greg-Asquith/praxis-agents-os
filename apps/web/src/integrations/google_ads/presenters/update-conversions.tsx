// apps/web/src/integrations/google_ads/presenters/update-conversions.tsx

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import { UpdateConversionsApproval } from "@/integrations/google_ads/components/update-conversions-approval"
import { UpdateConversionsOutcome } from "@/integrations/google_ads/components/update-conversions-outcome"
import {
  conversionsApproveLabel,
  conversionsBlock,
  conversionsDetails,
  conversionsPrompt,
  parseUpdateConversionsArgs,
  type UpdateConversionsArgs,
} from "@/integrations/google_ads/lib/update-conversions"
import {
  parseUpdateConversionsResult,
  type UpdateConversionsResult,
} from "@/integrations/google_ads/lib/update-conversions-result"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const googleAdsUpdateConversionsPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_update_conversions: defineIntegrationWriteVariant<
      UpdateConversionsArgs,
      UpdateConversionsResult
    >(googleAdsProvider, {
      copy: { verb: "Update", object: "conversions", effect: "updated" },
      approval: {
        title: "Change Conversion Settings",
        approveLabel: conversionsApproveLabel,
        parseArgs: parseUpdateConversionsArgs,
        prompt: conversionsPrompt,
        // An edit needs Google's answer, and problems follow what it last answered for.
        validateArgs: (value, checked) =>
          conversionsBlock(parseUpdateConversionsArgs(value), checked),
        renderInvalidDraft: true,
        renderFields: false,
        renderSummary: (value, fallback, onFieldEdit, disabled, controls) => (
          <UpdateConversionsApproval
            args={parseUpdateConversionsArgs(value) ?? fallback}
            checked={fallback}
            controls={controls}
            disabled={disabled}
            onFieldEdit={onFieldEdit}
          />
        ),
      },
      details: conversionsDetails,
      parseResult: parseUpdateConversionsResult,
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
            <UpdateConversionsOutcome result={result} />
          </div>
        ) : (
          <GoogleAdsFailureTargets
            targets={args?.items.map((item) => item.label) ?? []}
            description={description}
          />
        ),
      renderOutcome: (result) => <UpdateConversionsOutcome result={result} />,
      renderUnverifiedOutcome: (result) => <UpdateConversionsOutcome result={result} />,
    }),
  },
})
