// apps/web/src/integrations/meta_ads/presenters/create-ads.tsx

import { CreateAdsApproval, CreateAdsOutcome } from "@/integrations/meta_ads/components/create-ads"
import { MetaAdsFailureTargets } from "@/integrations/meta_ads/components/outcome-table"
import {
  adCount,
  approvalSummary,
  parseCreateAdsArgs,
  type CreateAdsArgs,
} from "@/integrations/meta_ads/lib/create-ads-args"
import { createAdsProblem } from "@/integrations/meta_ads/lib/create-ads-checks"
import {
  parseCreateAdsResult,
  type CreateAdsResult,
} from "@/integrations/meta_ads/lib/create-ads-result"
import { metaAdsProvider } from "@/integrations/meta_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const metaAdsCreateAdsPresenter = createIntegrationWritePresenter({
  variants: {
    meta_ads_create_ads: defineIntegrationWriteVariant<CreateAdsArgs, CreateAdsResult>(
      metaAdsProvider,
      {
        copy: {
          verb: "Create",
          object: "ads",
          effect: "created",
          check: "Check Ads Manager before creating these ads again.",
        },
        approval: {
          parseArgs: parseCreateAdsArgs,
          prompt: approvalSummary,
          // An ad Meta would reject can't be approved; the operator fixes it here or declines.
          validateArgs: (value) => createAdsProblem(parseCreateAdsArgs(value)),
          renderInvalidDraft: true,
          renderSummary: (value, fallback, onFieldEdit, disabled) => (
            <CreateAdsApproval
              args={parseCreateAdsArgs(value) ?? fallback}
              disabled={disabled}
              onFieldEdit={onFieldEdit}
            />
          ),
        },
        details: (args) => (args ? [{ label: "Ads", value: String(adCount(args)) }] : []),
        parseResult: parseCreateAdsResult,
        settledPartial: (result) => result.ads.some((ad) => ad.outcome === "failed"),
        settledUnverified: (result) => result.ads.some((ad) => ad.outcome === "unverified"),
        settledFailure: (result) =>
          result.ads.every((ad) => ad.outcome === "failed")
            ? "Meta Ads didn't create any of these ads."
            : null,
        renderFailure: (args, description, result) =>
          result ? (
            <div className="grid gap-3">
              <p className="text-destructive text-sm">{description}</p>
              <CreateAdsOutcome result={result} />
            </div>
          ) : (
            <MetaAdsFailureTargets
              description={description}
              targets={args?.ads.map((ad) => ad.name) ?? []}
            />
          ),
        renderOutcome: (result) => <CreateAdsOutcome result={result} />,
        renderUnverifiedOutcome: (result) => <CreateAdsOutcome result={result} />,
      }
    ),
  },
})
