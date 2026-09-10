// apps/web/src/integrations/notion/lib/write-args.ts

import { isRecord } from "@/lib/guards"

export type NotionWriteArgs = {
  /** Page title or the selected page's label, shown in card details. */
  label: string
}

export function parseNotionCreatePageArgs(value: unknown): NotionWriteArgs | null {
  if (!isRecord(value) || typeof value["title"] !== "string" || !value["title"].trim()) {
    return null
  }
  return { label: value["title"].trim() }
}

export function parseNotionPageArgs(value: unknown): NotionWriteArgs | null {
  if (!isRecord(value) || !isRecord(value["page"])) {
    return null
  }
  const label = value["page"]["label"]
  return { label: typeof label === "string" && label.trim() ? label.trim() : "Selected page" }
}
