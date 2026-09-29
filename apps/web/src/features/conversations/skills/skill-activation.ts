// apps/web/src/features/conversations/skills/skill-activation.ts

import type { Skill } from "@/features/skills/types"
import { isRecord } from "@/lib/guards"

export const LOAD_CAPABILITY_TOOL_NAME = "load_capability"
export const LOAD_SKILL_TOOL_NAME = "load_skill"
const INTERNAL_SKILL_CAPABILITY_PREFIX = "internal-"

type SkillActivationDisplay = Pick<Skill, "human_name" | "name">

export function loadedSkillNameFromArgs(args: unknown): string | null {
  const value = recordArg(args, "name")?.trim()
  if (!value) {
    return null
  }
  return value
}

// Internal skills ship with the platform, so their label derives from the kebab-case name.
export function internalSkillLabelFromCapabilityArgs(args: unknown): string | null {
  const capabilityId = recordArg(args, "id")
  if (!capabilityId?.startsWith(INTERNAL_SKILL_CAPABILITY_PREFIX)) {
    return null
  }
  const name = capabilityId.slice(INTERNAL_SKILL_CAPABILITY_PREFIX.length).trim()
  return name ? sentenceFromIdentifier(name) : null
}

export function skillActivationDisplayName(
  skill: SkillActivationDisplay | null | undefined,
  fallbackName: string
) {
  const humanName = skill?.human_name?.trim()
  if (humanName) {
    return humanName
  }
  return sentenceFromIdentifier(fallbackName)
}

function sentenceFromIdentifier(name: string) {
  const words = name.replaceAll("-", " ")
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function recordArg(args: unknown, key: string): string | null {
  const normalized = normalizeArgs(args)
  if (!isRecord(normalized)) {
    return null
  }
  const value = normalized[key]
  return typeof value === "string" ? value : null
}

function normalizeArgs(args: unknown) {
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
