// apps/web/src/integrations/google_ads/presenters/create-ads.tsx

import { CreateAdsApproval } from "@/integrations/google_ads/components/create-ads-approval"
import { CreateAdsOutcome } from "@/integrations/google_ads/components/create-ads-outcome"
import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import {
  createAdsApproveLabel,
  createAdsBlock,
  createAdsDetails,
  createAdsPrompt,
  parseCreateAdsArgs,
  type CreateAdsArgs,
} from "@/integrations/google_ads/lib/create-ads"
import {
  parseCreateAdsResult,
  type CreateAdsResult,
} from "@/integrations/google_ads/lib/create-ads-result"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const googleAdsCreateAdsPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_create_ads: defineIntegrationWriteVariant<CreateAdsArgs, CreateAdsResult>(
      googleAdsProvider,
      {
        copy: { verb: "Create", object: "search ads", effect: "created" },
        approval: {
          title: "Create Search Ads",
          approveLabel: createAdsApproveLabel,
          parseArgs: parseCreateAdsArgs,
          prompt: createAdsPrompt,
          // Problems follow the edited copy, and an edit needs Google's answer, so approval waits.
          validateArgs: (value, checked) => createAdsBlock(parseCreateAdsArgs(value), checked),
          renderInvalidDraft: true,
          renderFields: false,
          renderSummary: (value, fallback, onFieldEdit, disabled, controls) => (
            <CreateAdsApproval
              args={parseCreateAdsArgs(value) ?? fallback}
              checked={fallback}
              controls={controls}
              disabled={disabled}
              onFieldEdit={onFieldEdit}
            />
          ),
        },
        details: createAdsDetails,
        parseResult: parseCreateAdsResult,
        settledPartial: (result) => result.ads.some((ad) => ad.outcome === "failed"),
        settledUnverified: (result) => result.ads.some((ad) => ad.outcome === "unverified"),
        settledFailure: (result) =>
          result.ads.every((ad) => ad.outcome === "failed")
            ? "Google Ads didn't create any of these ads."
            : null,
        renderFailure: (args, description, result) =>
          result ? (
            <CreateAdsOutcome result={result} />
          ) : (
            <GoogleAdsFailureTargets
              targets={args?.ads.map((ad) => ad.headlines[0]?.text ?? "Ad") ?? []}
              description={description}
            />
          ),
        renderOutcome: (result) => <CreateAdsOutcome result={result} />,
        renderUnverifiedOutcome: (result) => <CreateAdsOutcome result={result} />,
      }
    ),
  },
})
