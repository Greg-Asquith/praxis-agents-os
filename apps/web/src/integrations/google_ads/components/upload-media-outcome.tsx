// apps/web/src/integrations/google_ads/components/upload-media-outcome.tsx

import { useMemo, useState } from "react"

import { WorkspaceFileThumbnail } from "@/components/tool-ui/workspace-file-thumbnail"
import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import { cellText } from "@/integrations/ads/lib/cell-text"
import { fileSize, fitsText } from "@/integrations/google_ads/lib/upload-media"
import {
  MEDIA_OUTCOME_BADGES,
  MEDIA_OUTCOME_LABELS,
  MEDIA_OUTCOME_TABS,
  mediaOutcomeSummary,
  type MediaKind,
  type MediaOutcome,
  type UploadMediaResult,
} from "@/integrations/google_ads/lib/upload-media-result"
import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"

const COLUMNS: DataColumn[] = [
  { key: "name", kind: "text", label: "Name", width: 260 },
  { key: "kind", kind: "text", label: "Kind", width: 120 },
  { key: "size", kind: "text", label: "Size", width: 100 },
  { key: "fits", kind: "text", label: "Fits", width: 180 },
  { key: "outcome", kind: "text", label: "Status", width: 130 },
  { key: "assetId", kind: "text", label: "Asset ID", hidden: true },
  { key: "uploadId", kind: "text", label: "Upload ID", hidden: true },
  { key: "details", kind: "text", label: "Details", hidden: true },
]

const RECOVERED = "Google's reply was lost, so the asset was found in the account."
const KIND_LABELS: Record<MediaKind, string> = {
  image: "Image",
  youtube_video: "YouTube video",
  video: "Video upload",
}

/** One row per image and video, opening on the failures when anything failed.

A video still processing names its upload, so a later call can finish it. */
export function UploadMediaOutcome({ result }: { result: UploadMediaResult }) {
  const [tab, setTab] = useState(
    result.uploads.some((upload) => upload.outcome === "failed") ? "failed" : "all"
  )
  const rows = useMemo(
    () =>
      result.uploads.map((upload, index) => ({
        assetId: upload.assetId ?? "",
        uploadId: upload.uploadId ?? "",
        details: [
          upload.message,
          upload.errorCode ? googleAdsTokenLabel(upload.errorCode) : null,
          upload.recovered ? RECOVERED : null,
        ]
          .filter(Boolean)
          .join(" · "),
        fits:
          upload.kind !== "image"
            ? "Video"
            : upload.outcome === "uploaded"
              ? fitsText(upload.fits)
              : "—",
        index,
        kind: KIND_LABELS[upload.kind],
        name: upload.name,
        outcome: MEDIA_OUTCOME_LABELS[upload.outcome],
        size:
          upload.sizeBytes === null
            ? ""
            : fileSize(upload.kind === "image" ? "image" : "video", upload.sizeBytes),
        token: upload.outcome,
      })),
    [result.uploads]
  )
  return (
    <DataTable
      activeTab={tab}
      columns={COLUMNS}
      exportFilename="google-ads-media-upload.csv"
      onTabChange={setTab}
      pageSize={25}
      renderCell={(column, row) => {
        if (column.key === "outcome")
          return (
            <Badge variant={MEDIA_OUTCOME_BADGES[row["token"] as MediaOutcome]}>
              {cellText(row["outcome"])}
            </Badge>
          )
        const upload = result.uploads[Number(row["index"])]
        if (column.key !== "name" || !upload) return null
        return (
          <span className="flex min-w-0 items-center gap-2">
            {upload.fileId ? (
              <WorkspaceFileThumbnail
                className="size-8"
                fileId={upload.fileId}
                kind={upload.kind === "image" ? "image" : "video"}
                label={upload.name}
                revisionId={upload.revisionId}
              />
            ) : null}
            <span className="grid gap-0.5 whitespace-normal">
              <span className="wrap-anywhere">{upload.name}</span>
              {upload.outcome === "processing" ? (
                <span className="text-muted-foreground text-xs wrap-anywhere">
                  {cellText(row["details"])}
                  {upload.uploadId ? ` Upload ID ${upload.uploadId}.` : ""}
                </span>
              ) : upload.outcome !== "uploaded" && upload.outcome !== "linked" && row["details"] ? (
                <span className="text-destructive text-xs wrap-anywhere">
                  {cellText(row["details"])}
                </span>
              ) : null}
            </span>
          </span>
        )
      }}
      rowNoun={["upload", "uploads"]}
      rows={rows}
      summary={<span>{mediaOutcomeSummary(result.uploads)}</span>}
      tabs={MEDIA_OUTCOME_TABS}
    />
  )
}
