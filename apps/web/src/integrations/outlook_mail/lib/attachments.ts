// apps/web/src/integrations/outlook_mail/lib/attachments.ts

import { nodeText } from "@/components/tool-ui/untrusted-node"
import { isNonNegativeInteger, isRecord } from "@/lib/guards"

export type OutlookAttachmentContent = {
  contentType: string | null
  markdown: string
  name: string
  sizeBytes: number | null
  truncated: boolean
}

export function parseAttachmentContent(value: unknown): OutlookAttachmentContent | null {
  if (!isRecord(value) || typeof value["truncated"] !== "boolean") return null
  const name = nodeText(value["name"])
  const markdown = nodeText(value["markdown"])
  if (name === null || markdown === null) return null
  const size = value["size_bytes"]
  return {
    contentType: nodeText(value["content_type"]),
    markdown,
    name,
    sizeBytes: isNonNegativeInteger(size) ? size : null,
    truncated: value["truncated"],
  }
}
