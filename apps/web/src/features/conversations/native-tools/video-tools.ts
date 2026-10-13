// apps/web/src/features/conversations/native-tools/video-tools.ts

import { isVideoAttachmentMediaType } from "@/features/conversations/attachments"
import { videoSummary } from "@/features/files/format"
import { isFileProcessing } from "@/features/files/processing"
import type { WorkspaceFile } from "@/features/files/types"
import { formatBytes } from "@/lib/format"
import { isRecord } from "@/lib/guards"

export type VideoFileReference = {
  fileId: string
  name: string | null
}

// Video Files a tool result names, either at the top level or in a list such as `clips`.
export function videoFileReferences(value: unknown): VideoFileReference[] | null {
  if (!isRecord(value)) {
    return null
  }
  const single = videoFileReference(value)
  if (single) {
    return [single]
  }
  const references = Object.values(value)
    .filter((item) => Array.isArray(item))
    .flatMap((items: unknown[]) => items.map(videoFileReference))
    .filter((reference) => reference !== null)
  return references.length > 0 ? references : null
}

function videoFileReference(value: unknown): VideoFileReference | null {
  if (
    !isRecord(value) ||
    typeof value["file_id"] !== "string" ||
    typeof value["media_type"] !== "string" ||
    !isVideoAttachmentMediaType(value["media_type"])
  ) {
    return null
  }
  return {
    fileId: value["file_id"],
    name: typeof value["name"] === "string" ? value["name"] : null,
  }
}

// The chip and card label for a video: preparing, failed, or its measurement.
export function videoFileStatus(file: WorkspaceFile | undefined) {
  if (!file || isFileProcessing(file.processing_status)) {
    return { kind: "preparing" as const, label: "Preparing video" }
  }
  if (file.processing_status === "error") {
    return { kind: "error" as const, label: file.processing_error ?? "Couldn't prepare video" }
  }
  return {
    kind: "ready" as const,
    label: file.video ? videoSummary(file.video) : formatBytes(file.size_bytes),
  }
}
