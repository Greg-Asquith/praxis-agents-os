// apps/web/src/integrations/notion/lib/read-results.ts

import { nodeText } from "@/components/tool-ui/untrusted-node"
import type { DataColumn, DataRow } from "@/components/ui/data-table"
import { humanizeKey } from "@/lib/format"
import { isRecord } from "@/lib/guards"

const RECORD_KEYS = new Set([
  "reference",
  "title",
  "url",
  "last_edited_time",
  "properties",
  "properties_truncated",
])
const TITLE_COLUMN_KEY = "notion:title"
const UPDATED_COLUMN_KEY = "notion:last-edited-time"
const URL_COLUMN_KEY = "notion:url"
const FENCE_START = /^\s*(`{3,}|~{3,})/
const MARKDOWN_BLOCK_START = /^\s*(?:#{1,6}\s|>|[-+*]\s|\d+[.)]\s|`{3,}|~{3,}|---(?:\s|$))/
const NOTION_EMPTY_BLOCK = /^\s*<empty-block\s*\/>\s*$/
const NOTION_ESCAPED_MARKDOWN = /\\([\\`*_[\]#~])/g
const NOTION_DATE_KEYS = new Set(["start", "end", "time_zone"])

export type NotionSearchData = {
  coverageNote: string
  hasMore: boolean
  items: NotionSearchItem[]
  raw: Record<string, unknown>
}

export type NotionSearchItem = {
  kind: "page" | "data_source"
  lastEditedTime: string
  raw: Record<string, unknown>
  title: string
  url: string
}

export type NotionPageData = {
  bytesReturned: number
  markdown: string
  providerTruncated: boolean
  raw: Record<string, unknown>
  sourceUpdatedAt: string
  title: string
  truncated: boolean
  unknownBlockCount: number
  url: string
}

export type NotionQueryData = {
  columns: DataColumn[]
  hasMore: boolean
  incomplete: boolean
  propertiesTruncated: boolean
  raw: Record<string, unknown>
  rows: DataRow[]
}

type NotionRecord = {
  lastEditedTime: string
  properties: Record<string, unknown>
  propertiesTruncated: boolean
  raw: Record<string, unknown>
  title: string
  url: string
}

export function parseSearchData(value: unknown): NotionSearchData | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["items"]) ||
    typeof value["coverage_note"] !== "string" ||
    typeof value["has_more"] !== "boolean"
  ) {
    return null
  }
  const items = value["items"].map(parseSearchItem)
  if (!items.every((item): item is NotionSearchItem => item !== null)) {
    return null
  }
  return {
    coverageNote: value["coverage_note"],
    hasMore: value["has_more"],
    items,
    raw: value,
  }
}

export function parsePageData(value: unknown): NotionPageData | null {
  if (
    !isRecord(value) ||
    typeof value["url"] !== "string" ||
    typeof value["source_updated_at"] !== "string" ||
    typeof value["bytes_returned"] !== "number" ||
    typeof value["truncated"] !== "boolean" ||
    typeof value["provider_truncated"] !== "boolean" ||
    typeof value["unknown_block_count"] !== "number"
  ) {
    return null
  }
  const title = nodeText(value["title"])
  const markdown = nodeText(value["markdown"])
  return title === null || markdown === null
    ? null
    : {
        bytesReturned: value["bytes_returned"],
        markdown: normalizeNotionMarkdown(markdown),
        providerTruncated: value["provider_truncated"],
        raw: value,
        sourceUpdatedAt: value["source_updated_at"],
        title,
        truncated: value["truncated"],
        unknownBlockCount: value["unknown_block_count"],
        url: value["url"],
      }
}

function normalizeNotionMarkdown(value: string): string {
  const lines = value.replaceAll("\r\n", "\n").split("\n")
  let fence: string | null = null
  const normalized = lines.map((line) => {
    const fenceMatch = FENCE_START.exec(line)
    if (fenceMatch) {
      const marker = fenceMatch[1]?.[0] ?? null
      fence = fence === null ? marker : fence === marker ? null : fence
      return line
    }
    if (fence !== null) {
      return line
    }
    if (NOTION_EMPTY_BLOCK.test(line)) {
      return ""
    }
    return line.replace(NOTION_ESCAPED_MARKDOWN, "$1")
  })

  let breakFence: string | null = null
  return normalized
    .map((line, index) => {
      const fenceMatch = FENCE_START.exec(line)
      if (fenceMatch) {
        const marker = fenceMatch[1]?.[0] ?? null
        breakFence = breakFence === null ? marker : breakFence === marker ? null : breakFence
        return line
      }
      const next = normalized[index + 1]
      if (
        breakFence !== null ||
        line.trim().length === 0 ||
        MARKDOWN_BLOCK_START.test(line) ||
        next === undefined ||
        next.trim().length === 0 ||
        MARKDOWN_BLOCK_START.test(next)
      ) {
        return line
      }
      return `${line}  `
    })
    .join("\n")
}

export function parseQueryData(value: unknown): NotionQueryData | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["records"]) ||
    typeof value["has_more"] !== "boolean" ||
    typeof value["incomplete"] !== "boolean"
  ) {
    return null
  }
  const records = value["records"].map(parseRecord)
  if (!records.every((record): record is NotionRecord => record !== null)) {
    return null
  }
  const table = notionRecordTable(records)
  return {
    columns: table.columns,
    hasMore: value["has_more"],
    incomplete: value["incomplete"],
    propertiesTruncated: records.some((record) => record.propertiesTruncated),
    raw: value,
    rows: table.rows,
  }
}

export function displayNotionValue(value: unknown): string {
  const text = nodeText(value)
  if (text !== null) {
    return text
  }
  if (Array.isArray(value)) {
    return value.map(displayNotionValue).join(", ")
  }
  if (isRecord(value)) {
    const keys = Object.keys(value)
    if (
      keys.length === 1 &&
      (typeof value["type"] === "string" || typeof value["unsupported_formula_type"] === "string")
    ) {
      return "Unavailable"
    }
    const notionDate = displayNotionDate(value, keys)
    if (notionDate !== null) {
      return notionDate
    }
    return Object.entries(value)
      .map(([key, item]) => `${humanizeKey(key)}: ${displayNotionValue(item)}`)
      .join(" · ")
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No"
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "bigint") {
    return String(value)
  }
  return value === null || value === undefined ? "—" : "Unsupported value"
}

function displayNotionDate(value: Record<string, unknown>, keys: string[]): string | null {
  if (keys.length === 0 || !keys.every((key) => NOTION_DATE_KEYS.has(key))) {
    return null
  }
  const start = nodeText(value["start"])
  if (start === null) {
    return null
  }
  const end = nodeText(value["end"])
  const timeZone = nodeText(value["time_zone"])
  const range = end === null ? start : `${start} – ${end}`
  return timeZone === null ? range : `${range} (${timeZone})`
}

function parseSearchItem(value: unknown): NotionSearchItem | null {
  if (
    !isRecord(value) ||
    (value["kind"] !== "page" && value["kind"] !== "data_source") ||
    typeof value["url"] !== "string" ||
    typeof value["last_edited_time"] !== "string"
  ) {
    return null
  }
  const title = nodeText(value["title"])
  return title === null
    ? null
    : {
        kind: value["kind"],
        lastEditedTime: value["last_edited_time"],
        raw: value,
        title,
        url: value["url"],
      }
}

function parseRecord(value: unknown): NotionRecord | null {
  if (
    !isRecord(value) ||
    typeof value["url"] !== "string" ||
    typeof value["last_edited_time"] !== "string" ||
    !isRecord(value["properties"]) ||
    typeof value["properties_truncated"] !== "boolean"
  ) {
    return null
  }
  const title = nodeText(value["title"])
  return title === null
    ? null
    : {
        lastEditedTime: value["last_edited_time"],
        properties: value["properties"],
        propertiesTruncated: value["properties_truncated"],
        raw: value,
        title,
        url: value["url"],
      }
}

function notionRecordTable(records: NotionRecord[]): { columns: DataColumn[]; rows: DataRow[] } {
  const dynamicColumns = new Map<string, string>()
  for (const record of records) {
    for (const property of Object.keys(record.properties)) {
      dynamicColumns.set(`notion:property:${property}`, property)
    }
    for (const key of Object.keys(record.raw)) {
      if (!RECORD_KEYS.has(key)) {
        dynamicColumns.set(`notion:field:${key}`, humanizeKey(key))
      }
    }
  }

  const rows = records.map((record) => {
    const row: DataRow = {
      [TITLE_COLUMN_KEY]: record.title,
      [UPDATED_COLUMN_KEY]: record.lastEditedTime,
      [URL_COLUMN_KEY]: record.url,
    }
    for (const [key, value] of Object.entries(record.properties)) {
      row[`notion:property:${key}`] = tableValue(value)
    }
    for (const [key, value] of Object.entries(record.raw)) {
      if (!RECORD_KEYS.has(key)) {
        row[`notion:field:${key}`] = tableValue(value)
      }
    }
    return row
  })

  return {
    columns: [
      { key: TITLE_COLUMN_KEY, kind: "text", label: "Page", width: 240 },
      { key: UPDATED_COLUMN_KEY, kind: "datetime", label: "Last edited" },
      { key: URL_COLUMN_KEY, kind: "link", label: "Notion link" },
      ...Array.from(dynamicColumns, ([key, label]): DataColumn => {
        const values = rows.flatMap((row) =>
          row[key] === null || row[key] === undefined ? [] : [row[key]]
        )
        return {
          key,
          kind:
            values.length > 0 && values.every((value) => typeof value === "number")
              ? "number"
              : "text",
          label,
        }
      }),
    ],
    rows,
  }
}

function tableValue(value: unknown): unknown {
  return typeof value === "boolean" || Array.isArray(value) || isRecord(value)
    ? displayNotionValue(value)
    : value
}
