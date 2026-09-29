// apps/web/src/features/conversations/skills/skill-activation.ts

import type { Skill } from "@/features/skills/types"
import { isRecord } from "@/lib/guards"

export const LOAD_CAPABILITY_TOOL_NAME = "load_capability"
const SKILL_CAPABILITY_PREFIX = "skill-"
const INTERNAL_SKILL_CAPABILITY_PREFIX = "internal-"

type SkillActivationDisplay = Pick<Skill, "human_name" | "id" | "name">

export function skillIdFromCapabilityArgs(args: unknown): string | null {
  return capabilitySuffix(args, SKILL_CAPABILITY_PREFIX)
}

// Internal skills ship with the platform, so their label derives from the kebab-case name.
export function internalSkillLabelFromCapabilityArgs(args: unknown): string | null {
  const name = capabilitySuffix(args, INTERNAL_SKILL_CAPABILITY_PREFIX)
  if (!name) {
    return null
  }
  const words = name.replaceAll("-", " ")
  return words.charAt(0).toUpperCase() + words.slice(1)
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

function capabilitySuffix(args: unknown, prefix: string): string | null {
  const normalized = normalizeCapabilityArgs(args)
  if (!isRecord(normalized)) {
    return null
  }

  const capabilityId = normalized["id"]
  if (typeof capabilityId !== "string" || !capabilityId.startsWith(prefix)) {
    return null
  }

  const suffix = capabilityId.slice(prefix.length).trim()
  return suffix.length > 0 ? suffix : null
}

function normalizeCapabilityArgs(args: unknown) {
  if (typeof args !== "string") {
    return args
  }

  try {
    const parsed: unknown = JSON.parse(args)
    return parsed
  } catch {
    return args
  }
}

function shortenSkillId(skillId: string) {
  return skillId.length > 12 ? skillId.slice(0, 8) : skillId
}
