// apps/web/src/integrations/outlook_mail/lib/attachments.ts

import { nodeText } from "@/components/tool-ui/untrusted-node"
import { parseTextMatches, type TextMatches } from "@/integrations/text-matches"
import { isNonNegativeInteger, isRecord } from "@/lib/guards"

export type OutlookAttachmentContent = {
  contentType: string | null
  endOffset: number
  markdown: string
  name: string
  offset: number
  sizeBytes: number | null
  totalBytes: number
  truncated: boolean
}

export type OutlookAttachmentMatches = TextMatches & { contentType: string | null; name: string }

export function parseAttachmentContent(value: unknown): OutlookAttachmentContent | null {
  if (!isRecord(value) || typeof value["truncated"] !== "boolean") return null
  const name = nodeText(value["name"])
  const markdown = nodeText(value["markdown"])
  const { offset, end_offset: endOffset, total_bytes: totalBytes } = value
  if (
    name === null ||
    markdown === null ||
    !isNonNegativeInteger(offset) ||
    !isNonNegativeInteger(endOffset) ||
    !isNonNegativeInteger(totalBytes) ||
    offset > endOffset ||
    endOffset > totalBytes
  )
    return null
  const size = value["size_bytes"]
  return {
    contentType: nodeText(value["content_type"]),
    endOffset,
    markdown,
    name,
    offset,
    sizeBytes: isNonNegativeInteger(size) ? size : null,
    totalBytes,
    truncated: value["truncated"],
  }
}

export function parseAttachmentMatches(value: unknown): OutlookAttachmentMatches | null {
  if (!isRecord(value)) return null
  const found = parseTextMatches(value)
  const name = nodeText(value["name"])
  if (found === null || name === null) return null
  return { ...found, contentType: nodeText(value["content_type"]), name }
}
