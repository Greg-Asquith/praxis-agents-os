// apps/web/src/integrations/google_ads/presenters/upload-media.tsx

import { GoogleAdsFailureTargets } from "@/integrations/google_ads/components/failure-targets"
import { UploadMediaApproval } from "@/integrations/google_ads/components/upload-media-approval"
import { UploadMediaOutcome } from "@/integrations/google_ads/components/upload-media-outcome"
import {
  parseUploadMediaArgs,
  uploadApproveLabel,
  uploadBlock,
  uploadPrompt,
  type UploadMediaArgs,
} from "@/integrations/google_ads/lib/upload-media"
import {
  parseUploadMediaResult,
  type UploadMediaResult,
} from "@/integrations/google_ads/lib/upload-media-result"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const googleAdsUploadMediaPresenter = createIntegrationWritePresenter({
  variants: {
    google_ads_upload_media: defineIntegrationWriteVariant<UploadMediaArgs, UploadMediaResult>(
      googleAdsProvider,
      {
        copy: {
          verb: "Upload",
          object: "media",
          effect: "uploaded",
          check: "Check the account's asset library before uploading again.",
        },
        approval: {
          title: "Upload Media to Google Ads",
          approveLabel: uploadApproveLabel,
          parseArgs: (value) => parseUploadMediaArgs(value),
          prompt: uploadPrompt,
          // An edited File list must be checked and pinned before it can be approved.
          validateArgs: (value) => uploadBlock(parseUploadMediaArgs(value)),
          renderInvalidDraft: true,
          // The card draws its own image table and video fields.
          renderFields: false,
          renderSummary: (value, fallback, onFieldEdit, disabled, controls) => (
            <UploadMediaApproval
              args={parseUploadMediaArgs(value, controls.retained) ?? fallback}
              controls={controls}
              disabled={disabled}
              onFieldEdit={onFieldEdit}
            />
          ),
        },
        parseResult: parseUploadMediaResult,
        settledPartial: (result) => result.uploads.some((upload) => upload.outcome === "failed"),
        settledUnverified: (result) =>
          result.uploads.some((upload) => upload.outcome === "unverified"),
        settledFailure: (result) =>
          result.uploads.every((upload) => upload.outcome === "failed")
            ? "Google Ads didn't take any of these uploads."
            : null,
        renderFailure: (args, description, result) =>
          result ? (
            <div className="grid gap-3">
              <p className="text-destructive text-sm">{description}</p>
              <UploadMediaOutcome result={result} />
            </div>
          ) : (
            <GoogleAdsFailureTargets
              targets={[
                ...(args?.images.filter((image) => !image.cancelled).map((image) => image.label) ??
                  []),
                ...(args?.videos ?? []),
              ]}
              description={description}
            />
          ),
        renderOutcome: (result) => <UploadMediaOutcome result={result} />,
        renderUnverifiedOutcome: (result) => <UploadMediaOutcome result={result} />,
      }
    ),
  },
})
