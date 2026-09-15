// apps/web/src/integrations/sharepoint/lib/file-content.ts

import { safeHttpUrl } from "@/components/tool-ui/field-resolution"
import { nodeText } from "@/components/tool-ui/untrusted-node"
import { isNonNegativeInteger, isRecord } from "@/lib/guards"

export type SharePointFileContent = {
  contentType: string
  markdown: string
  name: string
  sizeBytes: number
  truncated: boolean
  webUrl: string | null
}

export function parseFileContent(value: unknown): SharePointFileContent | null {
  if (!isRecord(value) || typeof value["truncated"] !== "boolean") return null
  const name = nodeText(value["name"])
  const markdown = nodeText(value["markdown"])
  const contentType = nodeText(value["content_type"])
  const webUrl = nodeText(value["web_url"])
  const sizeBytes = value["size_bytes"]
  if (
    name === null ||
    markdown === null ||
    contentType === null ||
    webUrl === null ||
    !isNonNegativeInteger(sizeBytes)
  )
    return null
  return {
    contentType,
    markdown,
    name,
    sizeBytes,
    truncated: value["truncated"],
    webUrl: safeHttpUrl(webUrl),
  }
}
