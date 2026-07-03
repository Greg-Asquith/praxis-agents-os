// apps/web/src/features/skills/format.ts

import type { Skill } from "@/features/skills/types"

export function skillIdentifierFromName(value: string) {
  return value
    .trim()
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .replace(/-+/g, "-")
}

export function humanNameFromIdentifier(value: string) {
  return value.replace(/-/g, " ")
}

export function skillDisplayName(skill: Skill) {
  return skill.human_name ?? skill.name
}
