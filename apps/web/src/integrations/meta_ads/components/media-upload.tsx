// apps/web/src/integrations/meta_ads/components/media-upload.tsx

import { WorkspaceFileThumbnail } from "@/components/tool-ui/workspace-file-thumbnail"
import { Button } from "@/components/ui/button"
import { MetaAdsApprovalSection } from "@/integrations/meta_ads/components/approval-section"
import { MetaAdsOutcomeTable } from "@/integrations/meta_ads/components/outcome-table"
import {
  uploadCountLine,
  type MediaUploadArgs,
  type MediaUploadResult,
} from "@/integrations/meta_ads/lib/media-upload"
import { formatBytes } from "@/lib/format"

const TYPE_LABELS = { image: "Image", video: "Video" } as const

export function MediaUploadApprovalSummary({
  args,
  disabled = false,
  onReview,
}: {
  args: MediaUploadArgs
  disabled?: boolean
  onReview?: (() => void) | undefined
}) {
  const reviewed = args.files.flatMap((file) => (file.reviewed ? [file.reviewed] : []))
  const destination = args.accountName ?? "the selected ad account"
  return (
    <div className="grid gap-3">
      {args.needsReview ? (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-muted-foreground text-sm">
            Check the changed Files to confirm Meta accepts them.
          </p>
          <Button
            disabled={disabled || !onReview}
            onClick={onReview}
            size="sm"
            type="button"
            variant="outline"
          >
            Check Files
          </Button>
        </div>
      ) : null}
      <MetaAdsApprovalSection
        ariaLabel="Files to upload"
        countLine={
          args.needsReview
            ? null
            : `${uploadCountLine(reviewed)} to ${destination}. This doesn't create ads or spend money.`
        }
      >
        <ul className="grid gap-2">
          {args.files.map((file) => (
            <li key={file.id} className="flex min-w-0 items-center gap-3">
              <WorkspaceFileThumbnail
                fileId={file.id}
                kind={file.reviewed?.mediaType ?? "image"}
                label={file.label}
                revisionId={file.reviewed?.revisionId ?? null}
              />
              <span className="grid min-w-0 gap-0.5">
                <span className="text-sm font-medium wrap-anywhere">
                  {file.reviewed?.name ?? file.label}
                </span>
                {file.reviewed ? (
                  <span className="text-muted-foreground text-xs">
                    {TYPE_LABELS[file.reviewed.mediaType]} · {formatBytes(file.reviewed.sizeBytes)}
                  </span>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
        <p className="text-muted-foreground text-xs">
          Approval uses these versions. If a File changes before the upload runs, it stops.
        </p>
      </MetaAdsApprovalSection>
    </div>
  )
}

export function MediaUploadOutcome({ result }: { result: MediaUploadResult }) {
  const rows = result.uploads.map((upload, index) => ({
    index,
    name: upload.name,
    type: TYPE_LABELS[upload.mediaType],
    mediaId: upload.mediaId ?? "",
    outcome: upload.outcome,
    details: [
      upload.message,
      upload.recovered
        ? "Meta's reply was lost, so the upload was found in the media library."
        : null,
    ]
      .filter(Boolean)
      .join(" "),
    errorCode: upload.errorCode,
  }))
  return (
    <MetaAdsOutcomeTable
      columns={[
        { key: "name", kind: "text", label: "File" },
        { key: "type", kind: "text", label: "Type" },
        { key: "mediaId", kind: "id", label: "Media ID" },
      ]}
      rows={rows}
      exportFilename="meta-ads-media-upload.csv"
      renderCell={(column, row) => {
        const upload = column.key === "name" ? result.uploads[Number(row["index"])] : undefined
        if (!upload) return null
        return (
          <span className="flex min-w-0 items-center gap-2">
            <WorkspaceFileThumbnail
              className="size-9"
              fileId={upload.fileId}
              kind={upload.mediaType}
              label={upload.name}
              revisionId={upload.revisionId}
            />
            <span className="wrap-anywhere">{upload.name}</span>
          </span>
        )
      }}
    />
  )
}
