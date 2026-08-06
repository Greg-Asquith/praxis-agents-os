// apps/web/src/features/conversations/native-tools/completion-tool.ts

import { normalizeRecord } from "@/lib/guards"

export const REPORT_COMPLETION_TOOL_NAME = "report_completion"

export type CompletionReport = {
  status: "pass" | "fail"
  summary: string
  evidence: string[]
}

export function completionReport(value: unknown): CompletionReport | null {
  const outer = normalizeRecord(value)
  const record = outer ? (normalizeRecord(outer["return_value"]) ?? outer) : null
  if (!record) {
    return null
  }

  const status = record["status"]
  const summary = record["summary"]
  const evidence = record["evidence"]
  if (
    (status !== "pass" && status !== "fail") ||
    typeof summary !== "string" ||
    !summary.trim() ||
    !Array.isArray(evidence) ||
    evidence.some((item) => typeof item !== "string" || !item.trim())
  ) {
    return null
  }

  return {
    status,
    summary: summary.trim(),
    evidence: evidence.map((item) => (item as string).trim()),
  }
}
