// apps/web/src/integrations/meta_ads/presenters/create-ad-set.tsx

import { CreateAdSetApproval } from "@/integrations/meta_ads/components/ad-set-summary"
import { CreatedObjectOutcome } from "@/integrations/meta_ads/components/create-summary"
import { MetaAdsFailureTargets } from "@/integrations/meta_ads/components/outcome-table"
import {
  adSetPrompt,
  createAdSetProblem,
  parseCreateAdSetArgs,
  type CreateAdSetArgs,
} from "@/integrations/meta_ads/lib/create-ad-set"
import {
  parseCreatedObject,
  type CreatedObjectResult,
} from "@/integrations/meta_ads/lib/create-summary"
import { metaAdsProvider } from "@/integrations/meta_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const metaAdsCreateAdSetPresenter = createIntegrationWritePresenter({
  variants: {
    meta_ads_create_ad_set: defineIntegrationWriteVariant<CreateAdSetArgs, CreatedObjectResult>(
      metaAdsProvider,
      {
        copy: {
          verb: "Create",
          object: "ad set",
          effect: "created",
          check: "Check Ads Manager before creating this ad set again.",
        },
        approval: {
          parseArgs: parseCreateAdSetArgs,
          prompt: adSetPrompt,
          validateArgs: (value) => createAdSetProblem(parseCreateAdSetArgs(value)),
          renderInvalidDraft: true,
          renderSummary: (value, fallback, onFieldEdit, disabled) => (
            <CreateAdSetApproval
              args={parseCreateAdSetArgs(value) ?? fallback}
              disabled={disabled}
              onFieldEdit={onFieldEdit}
            />
          ),
        },
        details: (args) => (args ? [{ label: "Campaign", value: args.campaignName }] : []),
        parseResult: (value) => parseCreatedObject(value, "ad_set", "adset_id"),
        settledUnverified: (result) => result.outcome === "unverified",
        settledFailure: (result) =>
          result.outcome === "failed" ? "Meta Ads didn't create this ad set." : null,
        renderFailure: (args, description, result) =>
          result ? (
            <div className="grid gap-3">
              <p className="text-destructive text-sm">{description}</p>
              <CreatedObjectOutcome result={result} type="adset" />
            </div>
          ) : (
            <MetaAdsFailureTargets description={description} targets={args ? [args.name] : []} />
          ),
        renderOutcome: (result) => <CreatedObjectOutcome result={result} type="adset" />,
        renderUnverifiedOutcome: (result) => <CreatedObjectOutcome result={result} type="adset" />,
      }
    ),
  },
})
