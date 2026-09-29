// apps/web/src/features/conversations/native-tools/skill-tools.ts

import { normalizeToolArgs } from "@/features/conversations/message-parts"
import { isRecord } from "@/lib/guards"

export const SEARCH_SKILLS_TOOL_NAME = "search_skills"
export const CREATE_SKILL_TOOL_NAME = "create_skill"
export const UPDATE_SKILL_TOOL_NAME = "update_skill"

export type SkillToolSummary = {
  description: string
  human_name: string | null
  id: string | null
  name: string
  owner: string | null
  scope: "platform" | "workspace"
}

export type SearchSkillsToolResult = {
  skills: SkillToolSummary[]
  total: number
}

type SkillToolDocument = {
  filename: string
  name: string
}

export type LoadSkillToolResult = SkillToolSummary & {
  documents: SkillToolDocument[]
  instructions: string
}

export function skillToolLabel(skill: Pick<SkillToolSummary, "human_name" | "name">) {
  return skill.human_name?.trim() ?? skill.name
}

export function searchSkillsQueryArg(args: unknown): string | null {
  const record = normalizeToolArgs(args)
  if (!isRecord(record) || typeof record["query"] !== "string") {
    return null
  }
  const query = record["query"].trim()
  return query ? query : null
}

export function searchSkillsResult(value: unknown): SearchSkillsToolResult | null {
  const result = unwrapToolReturnValue(value)
  if (
    !isRecord(result) ||
    !Array.isArray(result["skills"]) ||
    typeof result["total"] !== "number"
  ) {
    return null
  }
  const skills = result["skills"].map(skillToolSummary).filter((skill) => skill !== null)
  if (skills.length !== result["skills"].length) {
    return null
  }
  return { skills, total: result["total"] }
}

export function loadSkillResult(value: unknown): LoadSkillToolResult | null {
  const result = unwrapToolReturnValue(value)
  const summary = skillToolSummary(result)
  if (!summary || !isRecord(result) || typeof result["instructions"] !== "string") {
    return null
  }
  const documents = Array.isArray(result["documents"])
    ? result["documents"].filter(isSkillToolDocument)
    : []
  return { ...summary, documents, instructions: result["instructions"] }
}

export function savedSkillResult(value: unknown): SkillToolSummary | null {
  const result = unwrapToolReturnValue(value)
  return isRecord(result) ? skillToolSummary(result["skill"]) : null
}

function skillToolSummary(value: unknown): SkillToolSummary | null {
  if (
    !isRecord(value) ||
    typeof value["name"] !== "string" ||
    typeof value["description"] !== "string" ||
    (value["scope"] !== "platform" && value["scope"] !== "workspace")
  ) {
    return null
  }
  return {
    description: value["description"],
    human_name: typeof value["human_name"] === "string" ? value["human_name"] : null,
    id: typeof value["id"] === "string" ? value["id"] : null,
    name: value["name"],
    owner: typeof value["owner"] === "string" ? value["owner"] : null,
    scope: value["scope"],
  }
}

function isSkillToolDocument(value: unknown): value is SkillToolDocument {
  return (
    isRecord(value) && typeof value["name"] === "string" && typeof value["filename"] === "string"
  )
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
