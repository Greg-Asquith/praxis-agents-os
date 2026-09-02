// apps/web/src/features/knowledge/status.ts

import type { KbDocument, KbDocumentDetail, KbProcessingStatus, KbSourceType } from "./types"

export const KB_STATUS_PRESENTATION: Record<
  KbProcessingStatus,
  { label: string; variant: "outline" | "warning" | "success" | "destructive" }
> = {
  pending: { label: "Queued", variant: "outline" },
  processing: { label: "Processing", variant: "warning" },
  ready: { label: "Ready", variant: "success" },
  error: { label: "Failed", variant: "destructive" },
}

export function hasActiveProcessing(
  documents: readonly Pick<KbDocument | KbDocumentDetail, "status">[]
) {
  return documents.some(
    (document) => document.status === "pending" || document.status === "processing"
  )
}

export function isRefreshableSource(sourceType: KbSourceType) {
  return sourceType === "url" || sourceType === "integration"
}

export function canReprocessDocument(document: Pick<KbDocument, "source_type" | "status">) {
  if (document.status === "pending" || document.status === "processing") {
    return false
  }
  return isRefreshableSource(document.source_type) || document.status === "error"
}
