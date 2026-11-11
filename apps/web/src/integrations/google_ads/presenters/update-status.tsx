// apps/web/src/integrations/google_ads/presenters/update-status.tsx

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import { StatusChangeApproval } from "@/integrations/google_ads/components/status-change-approval"
import { StatusChangeOutcome } from "@/integrations/google_ads/components/status-change-outcome"
import {
  parseStatusChangeArgs,
  statusAccountNames,
  statusApproveLabel,
  statusBlock,
  statusCounts,
  statusDetails,
  statusPrompt,
  statusRows,
  type StatusChangeArgs,
} from "@/integrations/google_ads/lib/status-change"
import {
  parseStatusChangeResult,
  type StatusChangeResult,
} from "@/integrations/google_ads/lib/status-change-result"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

function summaryOf(args: StatusChangeArgs) {
  const rows = statusRows(args, args)
  return { counts: statusCounts(rows), rows }
}

export const googleAdsUpdateStatusPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_update_status: defineIntegrationWriteVariant<StatusChangeArgs, StatusChangeResult>(
      googleAdsProvider,
      {
        copy: { verb: "Update", object: "status", effect: "updated" },
        approval: {
          title: "Turn Google Ads On or Off",
          approveLabel: (args) => statusApproveLabel(summaryOf(args).counts),
          parseArgs: parseStatusChangeArgs,
          prompt: (args) => {
            const { counts, rows } = summaryOf(args)
            return statusPrompt(counts, statusAccountNames(rows, args.accounts))
          },
          // Problems and the approve count follow the edited statuses, so approval waits on them.
          validateArgs: (value) => statusBlock(parseStatusChangeArgs(value)),
          renderInvalidDraft: true,
          // The card draws its own table, so the generic fields stay off.
          renderFields: false,
          renderSummary: (value, fallback, onFieldEdit, disabled) => (
            <StatusChangeApproval
              args={parseStatusChangeArgs(value) ?? fallback}
              disabled={disabled}
              onFieldEdit={onFieldEdit}
              proposed={fallback}
            />
          ),
        },
        details: statusDetails,
        parseResult: parseStatusChangeResult,
        settledPartial: (result) => result.objects.some((object) => object.outcome === "failed"),
        settledUnverified: (result) =>
          result.objects.some((object) => object.outcome === "unverified"),
        settledFailure: (result) =>
          result.objects.length > 0 && result.objects.every((object) => object.outcome === "failed")
            ? "Google Ads didn't make any of these changes."
            : null,
        renderFailure: (args, description, result) =>
          result ? (
            <div className="grid gap-3">
              <p className="text-destructive text-sm">{description}</p>
              <StatusChangeOutcome result={result} />
            </div>
          ) : (
            <GoogleAdsFailureTargets
              targets={args?.items.map((item) => item.label) ?? []}
              description={description}
            />
          ),
        renderOutcome: (result) => <StatusChangeOutcome result={result} />,
        renderUnverifiedOutcome: (result) => <StatusChangeOutcome result={result} />,
      }
    ),
  },
})
