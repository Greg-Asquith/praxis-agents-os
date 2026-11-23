// apps/web/src/integrations/sharepoint/lib/copy-result.ts

import { safeHttpUrl } from "@/components/tool-ui/field-resolution"
import { parseSavedFile } from "@/components/tool-ui/saved-file"
import { sharePointItem } from "@/integrations/sharepoint/lib/items"
import { isRecord } from "@/lib/guards"

export function parseCopyResult(value: unknown) {
  const saved = parseSavedFile(value)
  const source = isRecord(value) ? sharePointItem(value["source"]) : null
  if (saved === null || source?.kind !== "file") return null
  return { ...saved, source: { name: source.name, webUrl: safeHttpUrl(source.webUrl) } }
}
