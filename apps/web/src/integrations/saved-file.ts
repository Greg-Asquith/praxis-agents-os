// apps/web/src/integrations/saved-file.ts

import { nodeText } from "@/components/tool-ui/untrusted-node"
import { isNonNegativeInteger, isRecord } from "@/lib/guards"

const FILE_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export type SavedFile = {
  contentType: string
  fileHref: string
  fileId: string
  name: string
  sizeBytes: number
}

// Provider copies into Files share one result shape: file_id, name, content_type, size_bytes.
export function parseSavedFile(value: unknown): SavedFile | null {
  if (!isRecord(value)) return null
  const fileId = value["file_id"]
  const name = nodeText(value["name"])
  const contentType = nodeText(value["content_type"])
  const sizeBytes = value["size_bytes"]
  if (
    typeof fileId !== "string" ||
    !FILE_ID.test(fileId) ||
    name === null ||
    contentType === null ||
    !isNonNegativeInteger(sizeBytes)
  )
    return null
  return { contentType, fileHref: `/files?fileId=${fileId}`, fileId, name, sizeBytes }
}
