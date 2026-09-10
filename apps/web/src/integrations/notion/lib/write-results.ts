// apps/web/src/integrations/notion/lib/write-results.ts

import { isRecord } from "@/lib/guards"

export type NotionWriteKind = "create" | "content" | "properties"

export type NotionWriteResult = {
  appliedReplacements: number | null
  lastEditedTime: string | null
  pageTruncated: boolean | null
  title: string | null
  url: string | null
}

export function parseNotionWriteResult(
  value: unknown,
  kind: NotionWriteKind
): NotionWriteResult | null {
  if (!isRecord(value) || value["outcome"] !== "applied") {
    return null
  }

  if (kind === "create") {
    const lastEditedTime = requiredString(value["last_edited_time"])
    const title = value["title"]
    const url = requiredString(value["url"])
    const reference = referenceLabel(value["reference"])
    if (
      lastEditedTime === null ||
      typeof title !== "string" ||
      title.length === 0 ||
      url === null ||
      reference === null
    ) {
      return null
    }
    return { appliedReplacements: null, lastEditedTime, pageTruncated: null, title, url }
  }

  if (kind === "content") {
    const lastEditedTime = nullableString(value["last_edited_time"])
    const appliedReplacements = value["applied_replacements"]
    const pageTruncated = optionalBoolean(value["page_truncated"])
    const title = referenceLabel(value["reference"])
    if (
      lastEditedTime === undefined ||
      typeof appliedReplacements !== "number" ||
      !Number.isInteger(appliedReplacements) ||
      appliedReplacements < 1 ||
      typeof pageTruncated !== "boolean" ||
      title === null
    ) {
      return null
    }
    return { appliedReplacements, lastEditedTime, pageTruncated, title, url: null }
  }

  const lastEditedTime = requiredString(value["last_edited_time"])
  const url = requiredString(value["url"])
  const title = referenceLabel(value["reference"])
  if (lastEditedTime === null || url === null || title === null) {
    return null
  }
  return { appliedReplacements: null, lastEditedTime, pageTruncated: null, title, url }
}

function referenceLabel(value: unknown): string | null {
  return isRecord(value) && typeof value["label"] === "string" && value["label"].length > 0
    ? value["label"]
    : null
}

function requiredString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null
}

function nullableString(value: unknown): string | null | undefined {
  return value === null ? null : (requiredString(value) ?? undefined)
}

function optionalBoolean(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined
}
