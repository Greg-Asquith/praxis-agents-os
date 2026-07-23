// apps/web/src/features/conversations/skill-document-read.ts

import { isRecord, stringValue } from "@/lib/guards"

export const READ_SKILL_DOCUMENT_TOOL_NAME = "read_skill_document"

export type SkillDocumentReadArgs = {
  document: string | null
  skill: string | null
}

export function skillDocumentReadArgs(args: unknown): SkillDocumentReadArgs {
  const normalized = normalizeToolArgs(args)
  if (!isRecord(normalized)) {
    return { document: null, skill: null }
  }

  return {
    document: stringValue(normalized["document"]),
    skill: stringValue(normalized["skill"]),
  }
}

function normalizeToolArgs(args: unknown) {
  if (typeof args !== "string") {
    return args
  }

  try {
    return JSON.parse(args) as unknown
  } catch {
    return args
  }
}
