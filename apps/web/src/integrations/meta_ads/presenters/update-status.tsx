// apps/web/src/integrations/meta_ads/presenters/update-status.tsx

import { MetaAdsFailureTargets } from "@/integrations/meta_ads/components/outcome-table"
import {
  StatusApprovalSummary,
  StatusOutcome,
} from "@/integrations/meta_ads/components/status-change"
import {
  parseStatusChangeArgs,
  parseStatusChangeResult,
  statusChangeDetails,
  type StatusChangeArgs,
  type StatusChangeResult,
} from "@/integrations/meta_ads/lib/status-change"
import { metaAdsProvider } from "@/integrations/meta_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const metaAdsUpdateStatusPresenter = createIntegrationWritePresenter({
  variants: {
    meta_ads_update_status: defineIntegrationWriteVariant<StatusChangeArgs, StatusChangeResult>(
      metaAdsProvider,
      {
        copy: {
          verb: "Update",
          object: "status",
          effect: "updated",
          check: "Check Ads Manager before taking further action.",
        },
        approval: {
          parseArgs: parseStatusChangeArgs,
          prompt: (args) =>
            args.status === "ACTIVE"
              ? "Turning these on starts delivery and spends your ad budget."
              : "Pausing stops delivery. Nothing is deleted.",
          // Approval waits until an edited selection is checked, so its evidence is current.
          validateArgs: (value) =>
            parseStatusChangeArgs(value)?.needsReview
              ? "Check the changes before approving."
              : null,
          renderInvalidDraft: true,
          renderSummary: (value, fallback, _onFieldEdit, disabled, controls) => (
            <StatusApprovalSummary
              args={parseStatusChangeArgs(value) ?? fallback}
              disabled={disabled}
              onReview={controls.onReview}
            />
          ),
        },
        details: statusChangeDetails,
        parseResult: parseStatusChangeResult,
        settledUnverified: (result) =>
          result.objects.some((object) => object.outcome === "unverified"),
        settledFailure: (result) =>
          result.objects.every((object) => object.outcome === "failed")
            ? "Meta Ads didn't make any of these changes."
            : null,
        renderFailure: (args, description, result) =>
          result ? (
            <div className="grid gap-3">
              <p className="text-destructive text-sm">{description}</p>
              <StatusOutcome result={result} />
            </div>
          ) : (
            <MetaAdsFailureTargets
              targets={args?.targets.map((target) => target.name) ?? []}
              description={description}
            />
          ),
        renderOutcome: (result) => <StatusOutcome result={result} />,
        renderUnverifiedOutcome: (result) => <StatusOutcome result={result} />,
      }
    ),
  },
})
