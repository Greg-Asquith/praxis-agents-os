// apps/web/src/features/skills/components/skill-form-model.ts

import { humanNameFromIdentifier, skillIdentifierFromName } from "@/features/skills/format"
import type { Skill, SkillCreateRequest, SkillUpdateRequest } from "@/features/skills/types"
import type { FormValidationEntry } from "@/lib/forms"

export type SkillFormState = {
  description: string
  instructions: string
  isActive: "true" | "false"
  isFavorite: "true" | "false"
  name: string
}

export type SkillFormValidationEntry = FormValidationEntry

export function initialSkillFormState(skill: Skill | null): SkillFormState {
  return {
    description: skill?.description ?? "",
    instructions: skill?.instructions ?? "",
    isActive: skill?.is_active === false ? "false" : "true",
    isFavorite: skill?.is_favorite ? "true" : "false",
    name: skill?.human_name ?? humanNameFromIdentifier(skill?.name ?? ""),
  }
}

export function buildSkillPayload(
  state: SkillFormState,
  mode: "create"
): SkillCreateRequest | string
export function buildSkillPayload(state: SkillFormState, mode: "edit"): SkillUpdateRequest | string
export function buildSkillPayload(
  state: SkillFormState,
  _mode: "create" | "edit"
): SkillCreateRequest | SkillUpdateRequest | string {
  const firstValidationEntry = validateSkillFormState(state)[0]
  if (firstValidationEntry) {
    return firstValidationEntry.message
  }

  const visibleName = state.name.trim()

  return {
    description: state.description.trim(),
    human_name: visibleName,
    instructions: state.instructions.trim(),
    is_active: state.isActive === "true",
    is_favorite: state.isFavorite === "true",
    name: skillIdentifierFromName(visibleName),
  }
}

export function validateSkillFormState(state: SkillFormState): SkillFormValidationEntry[] {
  const entries: SkillFormValidationEntry[] = []
  const name = state.name.trim()
  const identifier = skillIdentifierFromName(name)
  const description = state.description.trim()
  const instructions = state.instructions.trim()

  if (!name) {
    entries.push({
      fieldId: "skill-name",
      label: "Name",
      message: "Name is required.",
    })
  } else if (name.length > 255) {
    entries.push({
      fieldId: "skill-name",
      label: "Name",
      message: "Name must be 255 characters or fewer.",
    })
  } else if (!identifier) {
    entries.push({
      fieldId: "skill-name",
      label: "Name",
      message: "Name must include at least one letter or number.",
    })
  } else if (identifier.length > 64) {
    entries.push({
      fieldId: "skill-name",
      label: "Name",
      message: "Name is too long; the generated agent identifier must be 64 characters or fewer.",
    })
  }

  if (!description) {
    entries.push({
      fieldId: "skill-description",
      label: "Description",
      message: "Description is required.",
    })
  } else if (description.length > 1024) {
    entries.push({
      fieldId: "skill-description",
      label: "Description",
      message: "Description must be 1,024 characters or fewer.",
    })
  }

  if (!instructions) {
    entries.push({
      fieldId: "skill-instructions",
      label: "Instructions",
      message: "Instructions are required.",
    })
  } else if (instructions.length > 20000) {
    entries.push({
      fieldId: "skill-instructions",
      label: "Instructions",
      message: "Instructions must be 20,000 characters or fewer.",
    })
  }

  return entries
}

export function isSkillFormDirty(current: SkillFormState, initial: SkillFormState) {
  return (
    current.name !== initial.name ||
    current.description !== initial.description ||
    current.instructions !== initial.instructions ||
    current.isActive !== initial.isActive ||
    current.isFavorite !== initial.isFavorite
  )
}
