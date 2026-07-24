// apps/web/tests/features/conversations/kb-tools.test.ts

import { describe, expect, it } from "vitest"

import {
  readDocumentResult,
  searchKnowledgeQueryArg,
  searchKnowledgeResult,
} from "@/features/conversations/native-tools/kb-tools"

describe("search_knowledge results", () => {
  it("parses hits with plain and untrusted content", () => {
    const result = searchKnowledgeResult({
      query: "quarterly reviews",
      results: [
        {
          document_id: "doc-1",
          document_title: "Access policy",
          source_type: "manual",
          is_private: false,
          content: "Quarterly reviews are required.",
        },
        {
          document_id: "doc-2",
          document_title: "Imported handbook",
          source_type: "url",
          is_private: true,
          content: {
            node: "praxis_untrusted",
            source_kind: "kb",
            source_ref: "chunk:chunk-2",
            content: "External wording.",
          },
        },
      ],
      total: 2,
      used_lexical_fallback: false,
    })

    expect(result).not.toBeNull()
    expect(result?.total).toBe(2)
    expect(result?.results[0]?.content).toBe("Quarterly reviews are required.")
    expect(result?.results[1]?.source_type).toBe("url")
  })

  it("unwraps return_value envelopes", () => {
    const result = searchKnowledgeResult({
      return_value: { query: "policy", results: [], total: 0, used_lexical_fallback: true },
    })

    expect(result).not.toBeNull()
    expect(result?.used_lexical_fallback).toBe(true)
  })

  it("rejects unknown source types instead of inventing a badge", () => {
    expect(
      searchKnowledgeResult({
        query: "policy",
        results: [
          {
            document_id: "doc-1",
            document_title: "Access policy",
            source_type: "mystery",
            is_private: false,
            content: "text",
          },
        ],
        total: 1,
        used_lexical_fallback: false,
      })
    ).toBeNull()
    expect(searchKnowledgeResult({ query: "policy", results: [] })).toBeNull()
    expect(searchKnowledgeResult("plain text")).toBeNull()
  })
})

describe("read_document results", () => {
  it("parses a bounded document window", () => {
    const result = readDocumentResult({
      document_id: "doc-1",
      title: "Access policy",
      source_type: "manual",
      is_private: false,
      start: 0,
      end: 32,
      total_chars: 120,
      content: "# Policy\nQuarterly reviews.",
    })

    expect(result).not.toBeNull()
    expect(result?.end).toBe(32)
    expect(result?.total_chars).toBe(120)
  })

  it("rejects malformed windows and content shapes", () => {
    expect(readDocumentResult({ document_id: "doc-1", title: "Access policy" })).toBeNull()
    expect(
      readDocumentResult({
        document_id: "doc-1",
        title: "Access policy",
        source_type: "manual",
        is_private: false,
        start: 0,
        end: 32,
        total_chars: 120,
        content: { unexpected: true },
      })
    ).toBeNull()
  })
})

describe("search_knowledge args", () => {
  it("reads the trimmed query from object and JSON string args", () => {
    expect(searchKnowledgeQueryArg({ query: "  pricing tiers  " })).toBe("pricing tiers")
    expect(searchKnowledgeQueryArg('{"query": "pricing tiers"}')).toBe("pricing tiers")
    expect(searchKnowledgeQueryArg({ query: "   " })).toBeNull()
    expect(searchKnowledgeQueryArg(undefined)).toBeNull()
  })
})
