// apps/web/src/features/files/components/file-status-badge.ts

import { Loader2Icon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { fileProcessingStatusLabel } from "@/features/files/format"
import type { FileProcessingStatus } from "@/features/files/types"

export function FileStatusBadge({ status }: { status: FileProcessingStatus }) {
  if (status === "ready") {
    return <Badge variant="success">Ready</Badge>
  }

  if (status === "error") {
    return <Badge variant="destructive">Error</Badge>
  }

  return (
    <Badge variant="secondary">
      <Loader2Icon data-icon="inline-start" className="animate-spin" />
      {fileProcessingStatusLabel(status)}
    </Badge>
  )
}
