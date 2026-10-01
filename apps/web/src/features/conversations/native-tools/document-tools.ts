// apps/web/src/features/conversations/native-tools/document-tools.ts

import { nodeText } from "@/components/tool-ui/untrusted-node"
import type { FileEntitySnapshot } from "@/features/conversations/native-tools/file-tools"
import { WORKSPACE_FILE_MIME_TYPES } from "@/lib/file"
import { pluralize } from "@/lib/format"
import { isRecord, isStringArray } from "@/lib/guards"

const READ_TOOL_FORMATS = {
  read_presentation: "pptx",
  read_workbook: "xlsx",
  read_word_document: "docx",
} as const
const EDIT_TOOL_FORMATS = {
  edit_presentation: "pptx",
  edit_workbook: "xlsx",
  edit_word_document: "docx",
} as const
const CREATE_TOOL_FORMATS = {
  create_presentation: "pptx",
  create_workbook: "xlsx",
  create_word_document: "docx",
} as const
const READ_TABLE_TOOL_NAME = "read_table"
const VIEW_DOCUMENT_IMAGE_TOOL_NAME = "view_document_image"
const MAX_OUTLINE_ITEMS = 20
const MAX_READBACK_ITEMS = 50
const TABLE_PREVIEW_ROWS = 5
const TABLE_PREVIEW_COLUMNS = 6
const HEADING_STYLE = /^(Title|Heading \d)$/
const TITLE_PLACEHOLDERS = new Set(["title", "center_title"])

type OfficeFormat = "pptx" | "xlsx" | "docx"
type ReadToolName = keyof typeof READ_TOOL_FORMATS
type EditToolName = keyof typeof EDIT_TOOL_FORMATS
type CreateToolName = keyof typeof CREATE_TOOL_FORMATS
export type DocumentToolName =
  | ReadToolName
  | EditToolName
  | CreateToolName
  | typeof READ_TABLE_TOOL_NAME
  | typeof VIEW_DOCUMENT_IMAGE_TOOL_NAME
export type DocumentToolKind = "read" | "table" | "image" | "edit" | "create"

type DocumentFile = {
  fileId: string
  name: string
  revisionId: string
}

/** One read page: the part it covers, whether more remains, and an outline of what it holds. */
export type DocumentReadResult = {
  kind: "read"
  file: DocumentFile
  format: OfficeFormat
  part: string
  more: boolean
  outline: string[]
  hasTrackedChanges: boolean
}

export type DocumentTableResult = {
  kind: "table"
  file: DocumentFile
  columns: string[]
  preview: string[][]
  rowsRead: number
  totalRows: number
  more: boolean
  uncalculatedCount: number
}

export type DocumentImageResult = {
  kind: "image"
  file: DocumentFile
  imageRef: string
}

type DocumentReadbackItem = { label: string; value: string }

export type DocumentSaveResult = {
  kind: "edit" | "create"
  file: DocumentFile
  format: OfficeFormat
  revisionNumber: number
  folder: { id: string; name: string } | null
  warnings: string[]
  warningsOmitted: number
  changes: string[]
  changesOmitted: number
  readback: DocumentReadbackItem[]
  readbackTruncated: boolean
}

export type DocumentToolResult =
  DocumentReadResult | DocumentTableResult | DocumentImageResult | DocumentSaveResult

export function isDocumentToolName(name: string): name is DocumentToolName {
  return documentToolKind(name) !== null
}

export function documentToolKind(name: string): DocumentToolKind | null {
  if (name in READ_TOOL_FORMATS) return "read"
  if (name in EDIT_TOOL_FORMATS) return "edit"
  if (name in CREATE_TOOL_FORMATS) return "create"
  if (name === READ_TABLE_TOOL_NAME) return "table"
  if (name === VIEW_DOCUMENT_IMAGE_TOOL_NAME) return "image"
  return null
}

/** Parses a document tool's result, or returns null so the generic row renders it. */
export function documentToolResult(name: string, value: unknown): DocumentToolResult | null {
  const result = unwrapToolReturnValue(value)
  if (!isRecord(result)) return null
  const file = documentFile(result)
  if (!file) return null
  if (name === "read_presentation") return presentationRead(file, result)
  if (name === "read_workbook") return workbookRead(file, result)
  if (name === "read_word_document") return wordRead(file, result)
  if (name === READ_TABLE_TOOL_NAME) return tableRead(file, result)
  if (name === VIEW_DOCUMENT_IMAGE_TOOL_NAME) {
    return typeof result["image_ref"] === "string"
      ? { kind: "image", file, imageRef: result["image_ref"] }
      : null
  }
  if (name in EDIT_TOOL_FORMATS) {
    return saveResult("edit", EDIT_TOOL_FORMATS[name as EditToolName], file, result)
  }
  if (name in CREATE_TOOL_FORMATS) {
    return saveResult("create", CREATE_TOOL_FORMATS[name as CreateToolName], file, result)
  }
  return null
}

export function fileEntityFromDocumentResult(result: DocumentToolResult): FileEntitySnapshot {
  const contentType = "format" in result ? WORKSPACE_FILE_MIME_TYPES[result.format] : undefined
  return {
    ...(contentType ? { contentType } : {}),
    fileId: result.file.fileId,
    name: result.file.name,
  }
}

// Matches the stale base refusal text in the API's tools/documents/utils.py::_stale; keep in sync.
export function isStaleRevisionMessage(message: string): boolean {
  return message.includes("changed after you read it")
}

/** Returns the label of a File reference argument, such as the File a read targets. */
export function documentFileLabel(args: unknown, key = "file_id"): string | null {
  if (!isRecord(args)) return null
  const reference = args[key]
  return isRecord(reference) && typeof reference["label"] === "string" ? reference["label"] : null
}

export function documentCreateName(args: unknown): string | null {
  return isRecord(args) && typeof args["name"] === "string" && args["name"].trim()
    ? args["name"].trim()
    : null
}

/** Summarises an edit or create call's operations as one plain phrase per kind, with counts. */
export function documentOperationSummaries(args: unknown): string[] {
  if (!isRecord(args) || !Array.isArray(args["operations"])) return []
  const groups = new Map<string, { phrase: OperationPhrase; count: number; target: string }>()
  for (const operation of args["operations"]) {
    if (!isRecord(operation) || typeof operation["op"] !== "string") continue
    const phrase = OPERATION_PHRASES[operation["op"]] ?? OTHER_CHANGE
    const target = phrase.target ? stringField(operation, phrase.target) : ""
    const key = `${phrase === OTHER_CHANGE ? "other" : operation["op"]}:${target}`
    const group = groups.get(key) ?? { phrase, count: 0, target }
    group.count += phrase.count?.(operation) ?? 1
    groups.set(key, group)
  }
  return [...groups.values()].map(({ count, phrase, target }) => {
    const noun = pluralize(count, phrase.noun, phrase.plural)
    const suffix = target && phrase.preposition ? ` ${phrase.preposition} ${target}` : ""
    return `${phrase.verb} ${String(count)} ${noun}${suffix}`
  })
}

type OperationPhrase = {
  verb: string
  noun: string
  plural?: string
  count?: (operation: Record<string, unknown>) => number
  target?: string
  preposition?: string
}

const OTHER_CHANGE: OperationPhrase = { verb: "Make", noun: "other change" }

const OPERATION_PHRASES: Record<string, OperationPhrase> = {
  add_slide: { verb: "Add", noun: "slide" },
  duplicate_slide: { verb: "Duplicate", noun: "slide" },
  delete_slide: { verb: "Delete", noun: "slide" },
  move_slide: { verb: "Move", noun: "slide" },
  set_text: { verb: "Rewrite text in", noun: "shape" },
  replace_text: { verb: "Find and replace", noun: "phrase" },
  add_text_box: { verb: "Add", noun: "text box", plural: "text boxes" },
  set_table: { verb: "Update", noun: "table" },
  add_table: { verb: "Add", noun: "table" },
  add_image: { verb: "Add", noun: "image" },
  replace_image: { verb: "Replace", noun: "image" },
  add_chart: { verb: "Add", noun: "chart" },
  set_chart_data: { verb: "Update data in", noun: "chart" },
  set_notes: { verb: "Update notes on", noun: "slide" },
  set_geometry: { verb: "Move or resize", noun: "shape" },
  delete_shape: { verb: "Delete", noun: "shape" },
  set_cells: {
    verb: "Write",
    noun: "cell",
    count: (operation) => blockCellCount(operation["values"]),
    target: "sheet",
    preposition: "in",
  },
  append_rows: {
    verb: "Append",
    noun: "row",
    count: (operation) => arrayLength(operation["rows"]),
    target: "sheet",
    preposition: "to",
  },
  set_number_format: { verb: "Format numbers in", noun: "range" },
  set_style: { verb: "Style", noun: "range" },
  add_sheet: { verb: "Add", noun: "sheet" },
  rename_sheet: { verb: "Rename", noun: "sheet" },
  delete_sheet: { verb: "Delete", noun: "sheet" },
  merge_cells: { verb: "Merge", noun: "range" },
  set_column_width: { verb: "Resize", noun: "column range" },
  freeze_panes: { verb: "Change frozen panes on", noun: "sheet" },
  add_conditional_format: { verb: "Add", noun: "conditional format" },
  add_data_validation: { verb: "Add", noun: "dropdown" },
  define_name: { verb: "Define", noun: "name" },
  insert_paragraphs: {
    verb: "Insert",
    noun: "paragraph",
    count: (operation) => arrayLength(operation["paragraphs"]),
  },
  set_paragraph: { verb: "Rewrite", noun: "paragraph" },
  delete_paragraphs: {
    verb: "Delete",
    noun: "paragraph",
    count: (operation) => (typeof operation["count"] === "number" ? operation["count"] : 1),
  },
  insert_table: { verb: "Insert", noun: "table" },
  set_table_cells: {
    verb: "Write",
    noun: "table cell",
    count: (operation) => blockCellCount(operation["values"]),
  },
  page_break: { verb: "Add", noun: "page break" },
  set_header: { verb: "Update", noun: "header" },
  set_footer: { verb: "Update", noun: "footer" },
  add_comment: { verb: "Add", noun: "comment" },
}

function presentationRead(
  file: DocumentFile,
  result: Record<string, unknown>
): DocumentReadResult | null {
  const slides = recordArray(result["slides"])
  const slideCount = result["slide_count"]
  if (!slides || typeof slideCount !== "number") return null
  const numbers = slides.map((slide) => slide["number"]).filter(isNumber)
  return {
    kind: "read",
    file,
    format: "pptx",
    part: `${numberSpan(numbers, "Slide", "Slides")} of ${String(slideCount)}`,
    more: typeof result["next_slide"] === "number",
    outline: slides
      .slice(0, MAX_OUTLINE_ITEMS)
      .map((slide) => `${String(slide["number"])}. ${slideTitle(slide) ?? "Untitled slide"}`),
    hasTrackedChanges: false,
  }
}

function workbookRead(
  file: DocumentFile,
  result: Record<string, unknown>
): DocumentReadResult | null {
  const rows = recordArray(result["rows"])
  const sheet = result["sheet"]
  if (!rows || typeof sheet !== "string") return null
  const refs = rows.flatMap((row) => recordArray(row["cells"]) ?? []).map((cell) => cell["ref"])
  const range = cellSpan(refs.filter((ref): ref is string => typeof ref === "string"))
  return {
    kind: "read",
    file,
    format: "xlsx",
    part: range ? `${sheet}, ${range}` : `${sheet}, no cells with values`,
    more: typeof result["next_cursor"] === "number",
    outline: (recordArray(result["sheets"]) ?? [])
      .map((item) => item["name"])
      .filter((name): name is string => typeof name === "string")
      .slice(0, MAX_OUTLINE_ITEMS),
    hasTrackedChanges: false,
  }
}

function wordRead(file: DocumentFile, result: Record<string, unknown>): DocumentReadResult | null {
  const blocks = recordArray(result["blocks"])
  const blockCount = result["block_count"]
  if (!blocks || typeof blockCount !== "number") return null
  const nextStart = result["next_start"]
  const last = typeof nextStart === "number" ? nextStart : blockCount
  const first = last - blocks.length + 1
  return {
    kind: "read",
    file,
    format: "docx",
    part:
      blocks.length > 0
        ? `${numberSpan([first, last], "Block", "Blocks")} of ${String(blockCount)}`
        : `No blocks of ${String(blockCount)}`,
    more: typeof nextStart === "number",
    outline: blocks
      .filter((block) => typeof block["style"] === "string" && HEADING_STYLE.test(block["style"]))
      .map((block) => nodeText(block["text"]))
      .filter((text): text is string => Boolean(text?.trim()))
      .slice(0, MAX_OUTLINE_ITEMS),
    hasTrackedChanges: result["has_tracked_changes"] === true,
  }
}

function tableRead(
  file: DocumentFile,
  result: Record<string, unknown>
): DocumentTableResult | null {
  const columns = result["columns"]
  const rows = recordArray(result["rows"])
  const totalRows = result["total_rows"]
  if (!Array.isArray(columns) || !rows || typeof totalRows !== "number") return null
  const names = columns.map((column) => nodeText(column) ?? "")
  const shown = names.slice(0, TABLE_PREVIEW_COLUMNS)
  return {
    kind: "table",
    file,
    columns: names,
    preview: rows
      .slice(0, TABLE_PREVIEW_ROWS)
      .map((row) => shown.map((column) => cellText(row[column]))),
    rowsRead: rows.length,
    totalRows,
    more: typeof result["next_offset"] === "number",
    uncalculatedCount:
      typeof result["uncalculated_count"] === "number" ? result["uncalculated_count"] : 0,
  }
}

function saveResult(
  kind: "edit" | "create",
  format: OfficeFormat,
  file: DocumentFile,
  result: Record<string, unknown>
): DocumentSaveResult | null {
  const revisionNumber = result["revision_number"]
  const changes = recordArray(result["changes"])
  if (typeof revisionNumber !== "number" || !changes) return null
  const readback = isRecord(result["readback"]) ? result["readback"] : {}
  const items = READBACK[format](readback)
  return {
    kind,
    file,
    format,
    revisionNumber,
    folder: folderSummary(result["folder"]),
    warnings: isStringArray(result["warnings"]) ? result["warnings"] : [],
    warningsOmitted: count(result["warnings_omitted"]),
    changes: changes
      .map((change) => change["summary"])
      .filter((summary): summary is string => typeof summary === "string"),
    changesOmitted: count(result["changes_omitted"]),
    readback: items.slice(0, MAX_READBACK_ITEMS),
    readbackTruncated:
      items.length > MAX_READBACK_ITEMS ||
      Object.keys(readback).some((key) => key.endsWith("_truncated") && readback[key] === true),
  }
}

const READBACK: Record<
  OfficeFormat,
  (readback: Record<string, unknown>) => DocumentReadbackItem[]
> = {
  pptx: (readback) =>
    (recordArray(readback["slides"]) ?? []).map((slide) => ({
      label: `Slide ${String(slide["number"])}`,
      value: (recordArray(slide["shapes"]) ?? []).flatMap(shapeLines).join("\n"),
    })),
  xlsx: (readback) =>
    (recordArray(readback["blocks"]) ?? []).flatMap((block) =>
      (recordArray(block["cells"]) ?? []).map((cell) => ({
        label: `${String(block["sheet"])}!${String(cell["ref"])}`,
        value:
          cell["formula"] === undefined
            ? cellText(cell["value"])
            : `${cellText(cell["formula"])} (calculated when opened in Excel)`,
      }))
    ),
  docx: (readback) => [
    ...(recordArray(readback["blocks"]) ?? []).map(wordBlockReadback),
    ...storyReadback(readback["headers"], "header"),
    ...storyReadback(readback["footers"], "footer"),
    ...(recordArray(readback["comments"]) ?? []).map((comment) => ({
      label: "Comment",
      value: cellText(comment["text"]),
    })),
  ],
}

function wordBlockReadback(block: Record<string, unknown>): DocumentReadbackItem {
  const position = typeof block["index"] === "number" ? ` ${String(block["index"])}` : ""
  if (block["type"] === "table") {
    return { label: `Table${position}`, value: tableLines(block["rows"]).join("\n") }
  }
  const label = block["type"] === "paragraph" ? `Paragraph${position}` : "Content control"
  return { label, value: cellText(block["text"]) }
}

function storyReadback(stories: unknown, label: string): DocumentReadbackItem[] {
  return (recordArray(stories) ?? [])
    .filter((story) => story["text"] !== undefined)
    .map((story) => ({
      label: `Section ${String(story["section"])} ${label}`,
      value: cellText(story["text"]),
    }))
}

function shapeLines(shape: Record<string, unknown>): string[] {
  const paragraphs = (recordArray(shape["paragraphs"]) ?? []).map((paragraph) =>
    cellText(paragraph["text"])
  )
  return [...paragraphs, ...tableLines(shape["table"])].filter((line) => line.trim())
}

function tableLines(rows: unknown): string[] {
  if (!Array.isArray(rows)) return []
  return rows.map((row) => (Array.isArray(row) ? row.map(cellText).join(" | ") : ""))
}

function slideTitle(slide: Record<string, unknown>): string | null {
  for (const shape of recordArray(slide["shapes"]) ?? []) {
    const placeholder = shape["placeholder"]
    if (isRecord(placeholder) && TITLE_PLACEHOLDERS.has(String(placeholder["type"]))) {
      const title = shapeLines(shape).join(" ").trim()
      if (title) return title
    }
  }
  return null
}

function numberSpan(numbers: number[], singular: string, plural: string): string {
  if (numbers.length === 0) return `No ${plural.toLowerCase()}`
  const first = Math.min(...numbers)
  const last = Math.max(...numbers)
  if (first === last) return `${singular} ${String(first)}`
  if (last - first + 1 === numbers.length) return `${plural} ${String(first)}–${String(last)}`
  return `${String(numbers.length)} ${plural.toLowerCase()}`
}

function cellSpan(refs: string[]): string | null {
  const cells = refs
    .map((ref) => /^([A-Z]+)(\d+)$/.exec(ref))
    .filter((match) => match !== null)
    .map(([, column = "", row = ""]) => ({ column: columnNumber(column), row: Number(row) }))
  if (cells.length === 0) return null
  const columns = cells.map((cell) => cell.column)
  const rows = cells.map((cell) => cell.row)
  const start = `${columnLetters(Math.min(...columns))}${String(Math.min(...rows))}`
  const end = `${columnLetters(Math.max(...columns))}${String(Math.max(...rows))}`
  return start === end ? start : `${start}:${end}`
}

function columnNumber(letters: string): number {
  let total = 0
  for (let index = 0; index < letters.length; index += 1) {
    total = total * 26 + letters.charCodeAt(index) - 64
  }
  return total
}

function columnLetters(value: number): string {
  let letters = ""
  for (let remaining = value; remaining > 0; remaining = Math.floor((remaining - 1) / 26)) {
    letters = String.fromCharCode(65 + ((remaining - 1) % 26)) + letters
  }
  return letters
}

// File text stays plain text: untrusted nodes give their content, other values their string form.
function cellText(value: unknown): string {
  const text = nodeText(value)
  if (text !== null) return text
  if (typeof value === "number" || typeof value === "boolean") return String(value)
  return ""
}

function documentFile(result: Record<string, unknown>): DocumentFile | null {
  const { file_id: fileId, revision_id: revisionId } = result
  const name = nodeText(result["name"])
  if (typeof fileId !== "string" || name === null || typeof revisionId !== "string") {
    return null
  }
  return { fileId, name, revisionId }
}

function folderSummary(value: unknown): { id: string; name: string } | null {
  if (!isRecord(value) || typeof value["id"] !== "string" || typeof value["name"] !== "string") {
    return null
  }
  return { id: value["id"], name: value["name"] }
}

function recordArray(value: unknown): Record<string, unknown>[] | null {
  return Array.isArray(value) ? value.filter(isRecord) : null
}

function stringField(record: Record<string, unknown>, key: string): string {
  const value = record[key]
  return typeof value === "string" ? value : ""
}

function blockCellCount(value: unknown): number {
  return Array.isArray(value)
    ? value.reduce((total: number, row) => total + (Array.isArray(row) ? row.length : 1), 0)
    : 0
}

function arrayLength(value: unknown): number {
  return Array.isArray(value) ? value.length : 0
}

function count(value: unknown): number {
  return typeof value === "number" && value > 0 ? value : 0
}

function isNumber(value: unknown): value is number {
  return typeof value === "number"
}

// view_document_image returns the File fields beside the image content.
function unwrapToolReturnValue(value: unknown): unknown {
  const unwrapped = isRecord(value) && "return_value" in value ? value["return_value"] : value
  return Array.isArray(unwrapped) ? (unwrapped.find(isRecord) ?? null) : unwrapped
}
