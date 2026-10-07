// apps/web/src/integrations/meta_ads/presenters/upload-media.tsx

import {
  MediaUploadApprovalSummary,
  MediaUploadOutcome,
} from "@/integrations/meta_ads/components/media-upload"
import { MetaAdsFailureTargets } from "@/integrations/meta_ads/components/outcome-table"
import {
  parseMediaUploadArgs,
  parseMediaUploadResult,
  type MediaUploadArgs,
  type MediaUploadResult,
} from "@/integrations/meta_ads/lib/media-upload"
import { metaAdsProvider } from "@/integrations/meta_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const metaAdsUploadMediaPresenter = createIntegrationWritePresenter({
  variants: {
    meta_ads_upload_media: defineIntegrationWriteVariant<MediaUploadArgs, MediaUploadResult>(
      metaAdsProvider,
      {
        copy: {
          verb: "Upload",
          object: "media",
          effect: "uploaded",
          check: "Check the ad account's media library before uploading again.",
        },
        approval: {
          parseArgs: parseMediaUploadArgs,
          prompt: (args) =>
            `Upload these Files to ${args.accountName ?? "the selected Meta ad account"}'s media library, so ads can use them.`,
          // An edited File list must be checked and pinned before it can be approved.
          validateArgs: (value) =>
            parseMediaUploadArgs(value)?.needsReview ? "Check the Files before approving." : null,
          renderInvalidDraft: true,
          renderSummary: (value, fallback, _onFieldEdit, disabled, controls) => (
            <MediaUploadApprovalSummary
              args={parseMediaUploadArgs(value) ?? fallback}
              disabled={disabled}
              onReview={controls.onReview}
            />
          ),
        },
        parseResult: parseMediaUploadResult,
        settledPartial: (result) => result.uploads.some((upload) => upload.outcome === "failed"),
        settledUnverified: (result) =>
          result.uploads.some((upload) => upload.outcome === "unverified"),
        settledFailure: (result) =>
          result.uploads.every((upload) => upload.outcome === "failed")
            ? "Meta Ads didn't take any of these Files."
            : null,
        renderFailure: (args, description, result) =>
          result ? (
            <div className="grid gap-3">
              <p className="text-destructive text-sm">{description}</p>
              <MediaUploadOutcome result={result} />
            </div>
          ) : (
            <MetaAdsFailureTargets
              targets={args?.files.map((file) => file.label) ?? []}
              description={description}
            />
          ),
        renderOutcome: (result) => <MediaUploadOutcome result={result} />,
        renderUnverifiedOutcome: (result) => <MediaUploadOutcome result={result} />,
      }
    ),
  },
})
