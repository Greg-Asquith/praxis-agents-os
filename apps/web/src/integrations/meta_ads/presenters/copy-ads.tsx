// apps/web/src/integrations/meta_ads/presenters/copy-ads.tsx

import { CopyAdsApproval, CopyAdsOutcome } from "@/integrations/meta_ads/components/copy-ads"
import { MetaAdsFailureTargets } from "@/integrations/meta_ads/components/outcome-table"
import {
  copyAdsProblem,
  copySummary,
  parseCopyAdsArgs,
  parseCopyAdsResult,
  sourceName,
  type CopyAdsArgs,
  type CopyAdsResult,
} from "@/integrations/meta_ads/lib/copy-ads"
import { metaAdsProvider } from "@/integrations/meta_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const metaAdsCopyAdsPresenter = createIntegrationWritePresenter({
  variants: {
    meta_ads_copy_ads: defineIntegrationWriteVariant<CopyAdsArgs, CopyAdsResult>(metaAdsProvider, {
      copy: {
        verb: "Copy",
        object: "ads",
        effect: "copied",
        check: "Check Ads Manager before copying these ads again.",
      },
      approval: {
        parseArgs: parseCopyAdsArgs,
        prompt: copySummary,
        validateArgs: (value) => copyAdsProblem(parseCopyAdsArgs(value)),
        renderInvalidDraft: true,
        renderSummary: (value, fallback, onFieldEdit, disabled) => (
          <CopyAdsApproval
            args={parseCopyAdsArgs(value) ?? fallback}
            disabled={disabled}
            onFieldEdit={onFieldEdit}
          />
        ),
      },
      details: (args) => (args ? [{ label: "Copies", value: String(args.copies.length) }] : []),
      parseResult: parseCopyAdsResult,
      settledPartial: (result) => result.copies.some((copy) => copy.outcome === "failed"),
      settledUnverified: (result) => result.copies.some((copy) => copy.outcome === "unverified"),
      settledFailure: (result) =>
        result.copies.every((copy) => copy.outcome === "failed")
          ? "Meta Ads didn't copy any of these ads."
          : null,
      renderFailure: (args, description, result) =>
        result ? (
          <div className="grid gap-3">
            <p className="text-destructive text-sm">{description}</p>
            <CopyAdsOutcome result={result} />
          </div>
        ) : (
          <MetaAdsFailureTargets
            description={description}
            targets={args?.copies.map(sourceName) ?? []}
          />
        ),
      renderOutcome: (result) => <CopyAdsOutcome result={result} />,
      renderUnverifiedOutcome: (result) => <CopyAdsOutcome result={result} />,
    }),
  },
})
