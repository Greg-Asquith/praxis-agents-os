// apps/web/src/features/skills/components/skill-form-wizard-config.ts

import type { FormWizardStep } from "@/components/forms/form-wizard"
import type { FormValidationEntry } from "@/lib/forms"

export type SkillWizardStepId = "identity" | "instructions" | "documents" | "availability"

export const SKILL_CREATE_STEPS = [
  { id: "identity", title: "What does this skill do?" },
  { id: "instructions", title: "How should it work?" },
  {
    description: "You can add documents any time after creating the skill.",
    id: "documents",
    optional: true,
    title: "Reference documents",
  },
] as const satisfies readonly [
  FormWizardStep<SkillWizardStepId>,
  ...FormWizardStep<SkillWizardStepId>[],
]

export const SKILL_EDIT_STEPS = [
  { id: "identity", title: "What does this skill do?" },
  { id: "instructions", title: "How should it work?" },
  {
    description: "Add, replace, or remove the files agents can use with this skill.",
    id: "documents",
    optional: true,
    title: "Reference documents",
  },
  { id: "availability", title: "Availability" },
] as const satisfies readonly [
  FormWizardStep<SkillWizardStepId>,
  ...FormWizardStep<SkillWizardStepId>[],
]

const SKILL_STEP_FIELDS: Record<SkillWizardStepId, ReadonlySet<string>> = {
  availability: new Set(),
  documents: new Set(),
  identity: new Set(["skill-name", "skill-description"]),
  instructions: new Set(["skill-instructions"]),
}

export function skillValidationEntriesForStep(
  entries: readonly FormValidationEntry[],
  stepId: SkillWizardStepId
) {
  const stepFields = SKILL_STEP_FIELDS[stepId]
  return entries.filter((entry) => stepFields.has(entry.fieldId))
}

export function stepForSkillField(fieldId: string | undefined): SkillWizardStepId {
  if (fieldId && SKILL_STEP_FIELDS.instructions.has(fieldId)) {
    return "instructions"
  }
  return "identity"
}
