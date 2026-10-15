// apps/web/src/integrations/meta_ads/components/media-upload.tsx

import { PlusIcon } from "lucide-react"
import { useState } from "react"

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { WorkspaceFileThumbnail } from "@/components/tool-ui/workspace-file-thumbnail"
import { Button } from "@/components/ui/button"
import { EntitySearch } from "@/integrations/meta_ads/components/entity-search"
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
  disabled,
  onFieldEdit,
  onReview,
}: {
  args: MediaUploadArgs
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
  onReview?: (() => void) | undefined
}) {
  const [adding, setAdding] = useState(false)
  const reviewed = args.files.flatMap((file) => (file.reviewed ? [file.reviewed] : []))
  const destination = args.accountName ?? "the selected ad account"
  return (
    <div className="grid min-w-0 gap-3">
      {args.needsReview ? (
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-muted-foreground text-sm">
            Check the changed Files to confirm Meta accepts them.
          </p>
          <Button
            disabled={disabled || !onReview}
            onClick={onReview}
            type="button"
            variant="outline"
          >
            Check Files
          </Button>
        </div>
      ) : (
        <p className="text-sm">
          {uploadCountLine(reviewed)} to {destination}.{" "}
          <span className="text-muted-foreground">
            This doesn&apos;t create ads or spend money.
          </span>
        </p>
      )}
      <ul aria-label="Files to upload" className="divide-y overflow-hidden rounded-lg border">
        {args.files.map((file) => (
          <li key={file.id} className="flex min-w-0 items-center gap-3 p-3">
            <WorkspaceFileThumbnail
              fileId={file.id}
              kind={file.reviewed?.mediaType ?? "image"}
              label={file.label}
              revisionId={file.reviewed?.revisionId ?? null}
            />
            <span className="grid min-w-0 flex-1 gap-0.5">
              <span className="text-sm font-medium wrap-anywhere">
                {file.reviewed?.name ?? file.label}
              </span>
              {file.reviewed ? (
                <span className="text-muted-foreground text-sm">
                  {TYPE_LABELS[file.reviewed.mediaType]} · {formatBytes(file.reviewed.sizeBytes)}
                </span>
              ) : null}
            </span>
            <Button
              aria-label={`Remove ${file.reviewed?.name ?? file.label}`}
              disabled={disabled || args.files.length === 1}
              onClick={() => {
                onFieldEdit(
                  "files",
                  args.files.filter((other) => other.id !== file.id).map((other) => other.raw)
                )
              }}
              type="button"
              variant="ghost"
            >
              Remove
            </Button>
          </li>
        ))}
      </ul>
      {adding ? (
        <EntitySearch
          fieldKey="files"
          isTaken={(choice) =>
            args.files.some((file) => file.id === String(choice.value["entity_id"]))
          }
          label="Search Files"
          onChoose={(choice) => {
            onFieldEdit("files", [...args.files.map((file) => file.raw), choice.value])
            setAdding(false)
          }}
          toolName="meta_ads_upload_media"
        />
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <Button
          disabled={disabled}
          onClick={() => {
            setAdding(!adding)
          }}
          type="button"
          variant="outline"
        >
          <PlusIcon />
          {adding ? "Cancel" : "Add Files"}
        </Button>
        <p className="text-muted-foreground text-sm">
          Approval uses these versions. If a File changes before the upload runs, it stops.
        </p>
      </div>
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
