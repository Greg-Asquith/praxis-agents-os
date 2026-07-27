// apps/web/src/features/conversations/native-tools/memory-tools.ts

import { normalizeToolArgs } from "@/features/conversations/message-parts"
import type { MemoryKind, MemoryScope, MemoryType } from "@/features/memories/types"
import { isRecord } from "@/lib/guards"

export const SAVE_MEMORY_TOOL_NAME = "save_memory"
export const SEARCH_MEMORY_TOOL_NAME = "search_memory"
export const UPDATE_MEMORY_TOOL_NAME = "update_memory"
export const FORGET_MEMORY_TOOL_NAME = "forget_memory"

export type MemoryToolSummary = {
  id: string
  importance: number
  kind: MemoryKind
  memory_type: MemoryType
  scope: MemoryScope
  title: string
}

export type SaveMemoryToolResult =
  | { existing_memory: MemoryToolSummary | null; similarity: number; status: "near_duplicate" }
  | { memory: MemoryToolSummary; similarity: number | null; status: "created" | "reinforced" }

export type MemorySearchToolHit = {
  content: string
  content_truncated: boolean
  effective_confidence: number
  id: string
  kind: MemoryKind
  memory_type: MemoryType
  scope: MemoryScope
  title: string
}

export type SearchMemoryToolResult = {
  matches_found: number
  query: string
  results: MemorySearchToolHit[]
  results_truncated: boolean
  total: number
  used_lexical_fallback: boolean
}

export type UpdateMemoryToolResult = {
  memory: MemoryToolSummary
  status: "updated" | "superseded"
  superseded_memory_id: string | null
}

export type ForgetMemoryToolResult = {
  memory: MemoryToolSummary
  status: "archived" | "already_archived"
}

export function saveMemoryTitleArg(args: unknown): string | null {
  return stringArg(args, "title")
}

export function searchMemoryQueryArg(args: unknown): string | null {
  return stringArg(args, "query")
}

export function saveMemoryResult(value: unknown): SaveMemoryToolResult | null {
  const result = unwrapToolReturnValue(value)
  if (!isRecord(result)) {
    return null
  }
  if (result["status"] === "near_duplicate") {
    if (typeof result["similarity"] !== "number") {
      return null
    }
    let existing: MemoryToolSummary | null = null
    if (result["existing_memory"] !== null && result["existing_memory"] !== undefined) {
      existing = memoryToolSummary(result["existing_memory"])
      if (!existing) {
        return null
      }
    }
    return {
      existing_memory: existing,
      similarity: result["similarity"],
      status: "near_duplicate",
    }
  }
  if (result["status"] !== "created" && result["status"] !== "reinforced") {
    return null
  }
  const memory = memoryToolSummary(result["memory"])
  if (!memory) {
    return null
  }
  const similarity = result["similarity"]
  if (similarity !== null && similarity !== undefined && typeof similarity !== "number") {
    return null
  }
  return {
    memory,
    similarity: typeof similarity === "number" ? similarity : null,
    status: result["status"],
  }
}

export function searchMemoryResult(value: unknown): SearchMemoryToolResult | null {
  const result = unwrapToolReturnValue(value)
  if (!isRecord(result)) {
    return null
  }
  if (
    typeof result["query"] !== "string" ||
    !Array.isArray(result["results"]) ||
    typeof result["total"] !== "number" ||
    typeof result["matches_found"] !== "number" ||
    typeof result["results_truncated"] !== "boolean" ||
    typeof result["used_lexical_fallback"] !== "boolean"
  ) {
    return null
  }

  const hits = result["results"].map(memorySearchHit).filter((hit) => hit !== null)
  if (hits.length !== result["results"].length) {
    return null
  }

  return {
    matches_found: result["matches_found"],
    query: result["query"],
    results: hits,
    results_truncated: result["results_truncated"],
    total: result["total"],
    used_lexical_fallback: result["used_lexical_fallback"],
  }
}

export function updateMemoryResult(value: unknown): UpdateMemoryToolResult | null {
  const result = unwrapToolReturnValue(value)
  if (!isRecord(result)) {
    return null
  }
  if (result["status"] !== "updated" && result["status"] !== "superseded") {
    return null
  }
  const memory = memoryToolSummary(result["memory"])
  if (!memory) {
    return null
  }
  const supersededId = result["superseded_memory_id"]
  if (supersededId !== null && supersededId !== undefined && typeof supersededId !== "string") {
    return null
  }
  return {
    memory,
    status: result["status"],
    superseded_memory_id: typeof supersededId === "string" ? supersededId : null,
  }
}

export function forgetMemoryResult(value: unknown): ForgetMemoryToolResult | null {
  const result = unwrapToolReturnValue(value)
  if (!isRecord(result)) {
    return null
  }
  if (result["status"] !== "archived" && result["status"] !== "already_archived") {
    return null
  }
  const memory = memoryToolSummary(result["memory"])
  if (!memory) {
    return null
  }
  return { memory, status: result["status"] }
}

function memoryToolSummary(value: unknown): MemoryToolSummary | null {
  if (!isRecord(value)) {
    return null
  }
  if (
    typeof value["id"] !== "string" ||
    typeof value["title"] !== "string" ||
    !isMemoryScope(value["scope"]) ||
    !isMemoryKind(value["kind"]) ||
    !isMemoryType(value["memory_type"]) ||
    typeof value["importance"] !== "number"
  ) {
    return null
  }
  return {
    id: value["id"],
    importance: value["importance"],
    kind: value["kind"],
    memory_type: value["memory_type"],
    scope: value["scope"],
    title: value["title"],
  }
}

function memorySearchHit(value: unknown): MemorySearchToolHit | null {
  if (!isRecord(value)) {
    return null
  }
  if (
    typeof value["id"] !== "string" ||
    typeof value["title"] !== "string" ||
    typeof value["content"] !== "string" ||
    typeof value["content_truncated"] !== "boolean" ||
    !isMemoryScope(value["scope"]) ||
    !isMemoryKind(value["kind"]) ||
    !isMemoryType(value["memory_type"]) ||
    typeof value["effective_confidence"] !== "number"
  ) {
    return null
  }
  return {
    content: value["content"],
    content_truncated: value["content_truncated"],
    effective_confidence: value["effective_confidence"],
    id: value["id"],
    kind: value["kind"],
    memory_type: value["memory_type"],
    scope: value["scope"],
    title: value["title"],
  }
}

function isMemoryScope(value: unknown): value is MemoryScope {
  return value === "agent" || value === "user" || value === "workspace"
}

function isMemoryKind(value: unknown): value is MemoryKind {
  return value === "core" || value === "note"
}

function isMemoryType(value: unknown): value is MemoryType {
  return value === "fact" || value === "preference" || value === "episode" || value === "outcome"
}

function stringArg(args: unknown, key: string): string | null {
  const record = normalizeToolArgs(args)
  if (!isRecord(record)) {
    return null
  }
  const value = record[key]
  if (typeof value !== "string") {
    return null
  }
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

function unwrapToolReturnValue(value: unknown): unknown {
  if (isRecord(value)) {
    const returnValue = value["return_value"]
    if (isRecord(returnValue)) {
      return returnValue
    }
  }
  return value
}
