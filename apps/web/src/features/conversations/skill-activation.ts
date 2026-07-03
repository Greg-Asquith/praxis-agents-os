// apps/web/src/features/conversations/skill-activation.ts

import type { Skill } from "@/features/skills/types"
import { isRecord } from "@/lib/guards"

export const LOAD_CAPABILITY_TOOL_NAME = "load_capability"
const SKILL_CAPABILITY_PREFIX = "skill:"

type SkillActivationDisplay = Pick<Skill, "human_name" | "id" | "name">

export function skillIdFromCapabilityArgs(args: unknown): string | null {
  const normalized = normalizeCapabilityArgs(args)
  if (!isRecord(normalized)) {
    return null
  }

  const capabilityId = normalized["id"]
  if (typeof capabilityId !== "string" || !capabilityId.startsWith(SKILL_CAPABILITY_PREFIX)) {
    return null
  }

  const skillId = capabilityId.slice(SKILL_CAPABILITY_PREFIX.length).trim()
  return skillId.length > 0 ? skillId : null
}

export function skillActivationDisplayName(
  skill: SkillActivationDisplay | null | undefined,
  fallbackId: string
) {
  const humanName = skill?.human_name?.trim()
  if (humanName) {
    return humanName
  }

  const name = skill?.name.trim()
  if (name) {
    return name
  }

  return shortenSkillId(fallbackId)
}

function normalizeCapabilityArgs(args: unknown) {
  if (typeof args !== "string") {
    return args
  }

  try {
    return JSON.parse(args) as unknown
  } catch {
    return args
  }
}

function shortenSkillId(skillId: string) {
  return skillId.length > 12 ? skillId.slice(0, 8) : skillId
}
