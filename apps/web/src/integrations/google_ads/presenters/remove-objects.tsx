// apps/web/src/integrations/google_ads/presenters/remove-objects.tsx

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import { RemoveObjectsApproval } from "@/integrations/google_ads/components/remove-objects-approval"
import { RemoveObjectsOutcome } from "@/integrations/google_ads/components/remove-objects-outcome"
import {
  parseRemoveObjectsArgs,
  removalAccountNames,
  removalApproveLabel,
  removalBlock,
  removalCounts,
  removalDetails,
  removalPrompt,
  removalRows,
  type RemoveObjectsArgs,
} from "@/integrations/google_ads/lib/remove-objects"
import {
  parseRemoveObjectsResult,
  type RemoveObjectsResult,
} from "@/integrations/google_ads/lib/remove-objects-result"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

function summaryOf(args: RemoveObjectsArgs) {
  const rows = removalRows(args, args)
  return { counts: removalCounts(rows), rows }
}

export const googleAdsRemoveObjectsPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_remove_objects: defineIntegrationWriteVariant<
      RemoveObjectsArgs,
      RemoveObjectsResult
    >(googleAdsProvider, {
      copy: { verb: "Remove", object: "items", effect: "removed", destructive: true },
      approval: {
        title: "Remove Google Ads Items",
        approveLabel: (args) => removalApproveLabel(summaryOf(args).counts),
        parseArgs: parseRemoveObjectsArgs,
        prompt: (args) => {
          const { counts, rows } = summaryOf(args)
          return removalPrompt(counts, removalAccountNames(rows, args.accounts))
        },
        // Problems and the approve count follow the cancelled items, so approval waits on them.
        validateArgs: (value) => removalBlock(parseRemoveObjectsArgs(value)),
        renderInvalidDraft: true,
        // The card draws its own table, so the generic fields stay off.
        renderFields: false,
        renderSummary: (value, fallback, onFieldEdit, disabled) => (
          <RemoveObjectsApproval
            args={parseRemoveObjectsArgs(value) ?? fallback}
            disabled={disabled}
            onFieldEdit={onFieldEdit}
            proposed={fallback}
          />
        ),
      },
      details: removalDetails,
      parseResult: parseRemoveObjectsResult,
      settledPartial: (result) => result.objects.some((object) => object.outcome === "failed"),
      settledUnverified: (result) =>
        result.objects.some((object) => object.outcome === "unverified"),
      settledFailure: (result) =>
        result.objects.every((object) => object.outcome === "failed")
          ? "Google Ads didn't remove any of these items."
          : null,
      renderFailure: (args, description, result) =>
        result ? (
          <div className="grid gap-3">
            <p className="text-destructive text-sm">{description}</p>
            <RemoveObjectsOutcome result={result} />
          </div>
        ) : (
          <GoogleAdsFailureTargets
            targets={args?.items.map((item) => item.label) ?? []}
            description={description}
          />
        ),
      renderOutcome: (result) => <RemoveObjectsOutcome result={result} />,
      renderUnverifiedOutcome: (result) => <RemoveObjectsOutcome result={result} />,
    }),
  },
})
