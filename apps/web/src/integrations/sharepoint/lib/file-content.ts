// apps/web/src/integrations/sharepoint/lib/file-content.ts

import { safeHttpUrl } from "@/components/tool-ui/field-resolution"
import { nodeText } from "@/components/tool-ui/untrusted-node"
import { isNonNegativeInteger, isRecord } from "@/lib/guards"

export type SharePointFileContent = {
  contentType: string
  endOffset: number
  limitReached: boolean
  markdown: string
  name: string
  offset: number
  sizeBytes: number
  totalBytes: number
  truncated: boolean
  webUrl: string | null
}

export function parseFileContent(value: unknown): SharePointFileContent | null {
  if (
    !isRecord(value) ||
    typeof value["truncated"] !== "boolean" ||
    typeof value["limit_reached"] !== "boolean"
  )
    return null
  const name = nodeText(value["name"])
  const markdown = nodeText(value["markdown"])
  const contentType = nodeText(value["content_type"])
  const webUrl = nodeText(value["web_url"])
  const sizeBytes = value["size_bytes"]
  const offset = value["offset"]
  const endOffset = value["end_offset"]
  const totalBytes = value["total_bytes"]
  if (
    name === null ||
    markdown === null ||
    contentType === null ||
    webUrl === null ||
    !isNonNegativeInteger(sizeBytes) ||
    !isNonNegativeInteger(offset) ||
    !isNonNegativeInteger(endOffset) ||
    !isNonNegativeInteger(totalBytes) ||
    offset > endOffset ||
    endOffset > totalBytes
  )
    return null
  return {
    contentType,
    endOffset,
    limitReached: value["limit_reached"],
    markdown,
    name,
    offset,
    sizeBytes,
    totalBytes,
    truncated: value["truncated"],
    webUrl: safeHttpUrl(webUrl),
  }
}
