// apps/web/src/features/conversations/native-tools/kb-tools.ts

import { isUntrustedNode, type UntrustedNode } from "@/components/tool-ui/untrusted-node"
import { normalizeToolArgs } from "@/features/conversations/message-parts"
import type { KbSourceType } from "@/features/knowledge/types"
import { isRecord } from "@/lib/guards"

export const SEARCH_KNOWLEDGE_TOOL_NAME = "search_knowledge"
export const READ_DOCUMENT_TOOL_NAME = "read_document"

export type KnowledgeSearchHit = {
  content: string | UntrustedNode
  document_id: string
  document_title: string
  is_private: boolean
  source_type: KbSourceType
}

export type SearchKnowledgeToolResult = {
  query: string
  results: KnowledgeSearchHit[]
  total: number
  used_lexical_fallback: boolean
}

export type ReadDocumentToolResult = {
  content: string | UntrustedNode
  document_id: string
  end: number
  is_private: boolean
  source_type: KbSourceType
  start: number
  title: string
  total_chars: number
}

export function knowledgeChunkPreview(content: string | UntrustedNode): string {
  const text = typeof content === "string" ? content : content.content
  return text
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s{0,3}>\s?/gm, "")
    .replace(/^\s{0,3}[-*+]\s+/gm, "")
    .replace(/\*{1,3}|_{2,3}|~~/g, "")
    .replace(/\s+/g, " ")
    .trim()
}

export function searchKnowledgeQueryArg(args: unknown): string | null {
  const record = normalizeToolArgs(args)
  if (!isRecord(record) || typeof record["query"] !== "string") {
    return null
  }
  const query = record["query"].trim()
  return query ? query : null
}

export function searchKnowledgeResult(value: unknown): SearchKnowledgeToolResult | null {
  const result = unwrapToolReturnValue(value)
  if (!isRecord(result)) {
    return null
  }
  if (
    typeof result["query"] !== "string" ||
    !Array.isArray(result["results"]) ||
    typeof result["total"] !== "number" ||
    typeof result["used_lexical_fallback"] !== "boolean"
  ) {
    return null
  }

  const hits = result["results"].map(knowledgeSearchHit).filter((hit) => hit !== null)
  if (hits.length !== result["results"].length) {
    return null
  }

  return {
    query: result["query"],
    results: hits,
    total: result["total"],
    used_lexical_fallback: result["used_lexical_fallback"],
  }
}

export function readDocumentResult(value: unknown): ReadDocumentToolResult | null {
  const result = unwrapToolReturnValue(value)
  if (!isRecord(result)) {
    return null
  }
  if (
    typeof result["document_id"] !== "string" ||
    typeof result["title"] !== "string" ||
    !isKbSourceType(result["source_type"]) ||
    typeof result["is_private"] !== "boolean" ||
    typeof result["start"] !== "number" ||
    typeof result["end"] !== "number" ||
    typeof result["total_chars"] !== "number" ||
    !isKnowledgeContent(result["content"])
  ) {
    return null
  }

  return {
    content: result["content"],
    document_id: result["document_id"],
    end: result["end"],
    is_private: result["is_private"],
    source_type: result["source_type"],
    start: result["start"],
    title: result["title"],
    total_chars: result["total_chars"],
  }
}

function knowledgeSearchHit(value: unknown): KnowledgeSearchHit | null {
  if (!isRecord(value)) {
    return null
  }
  if (
    typeof value["document_id"] !== "string" ||
    typeof value["document_title"] !== "string" ||
    !isKbSourceType(value["source_type"]) ||
    typeof value["is_private"] !== "boolean" ||
    !isKnowledgeContent(value["content"])
  ) {
    return null
  }
  return {
    content: value["content"],
    document_id: value["document_id"],
    document_title: value["document_title"],
    is_private: value["is_private"],
    source_type: value["source_type"],
  }
}

function isKbSourceType(value: unknown): value is KbSourceType {
  return (
    value === "upload" ||
    value === "url" ||
    value === "manual" ||
    value === "conversation" ||
    value === "integration"
  )
}

function isKnowledgeContent(value: unknown): value is string | UntrustedNode {
  return typeof value === "string" || isUntrustedNode(value)
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
