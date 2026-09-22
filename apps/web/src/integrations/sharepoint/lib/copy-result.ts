// apps/web/src/integrations/sharepoint/lib/copy-result.ts

import { safeHttpUrl } from "@/components/tool-ui/field-resolution"
import { nodeText } from "@/components/tool-ui/untrusted-node"
import { sharePointItem } from "@/integrations/sharepoint/lib/items"
import { isNonNegativeInteger, isRecord } from "@/lib/guards"

const FILE_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export function parseCopyResult(value: unknown) {
  if (!isRecord(value)) return null
  const fileId = value["file_id"]
  const name = nodeText(value["name"])
  const contentType = nodeText(value["content_type"])
  const sizeBytes = value["size_bytes"]
  const source = sharePointItem(value["source"])
  if (
    typeof fileId !== "string" ||
    !FILE_ID.test(fileId) ||
    name === null ||
    contentType === null ||
    !isNonNegativeInteger(sizeBytes) ||
    source?.kind !== "file"
  )
    return null
  return {
    fileHref: `/files?fileId=${fileId}`,
    name,
    contentType,
    sizeBytes,
    source: { name: source.name, webUrl: safeHttpUrl(source.webUrl) },
  }
}
