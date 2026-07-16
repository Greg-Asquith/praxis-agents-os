import { describe, expect, it } from "vitest"

import { initialSkillFormState } from "@/features/skills/components/skill-form-model"
import {
  SKILL_CREATE_STEPS,
  SKILL_EDIT_STEPS,
  skillValidationEntriesForStep,
  stepForSkillField,
} from "@/features/skills/components/skill-form-wizard-config"
import type { FormValidationEntry } from "@/lib/forms"

const validationEntries: FormValidationEntry[] = [
  { fieldId: "skill-name", label: "Name", message: "Name is required." },
  {
    fieldId: "skill-description",
    label: "Description",
    message: "Description is required.",
  },
  {
    fieldId: "skill-instructions",
    label: "Instructions",
    message: "Instructions are required.",
  },
]

describe("skill wizard configuration", () => {
  it("keeps create at three steps and makes documents intermediate when editing", () => {
    expect(SKILL_CREATE_STEPS.map((step) => step.id)).toEqual([
      "identity",
      "instructions",
      "documents",
    ])
    expect(SKILL_EDIT_STEPS.map((step) => step.id)).toEqual([
      "identity",
      "instructions",
      "documents",
      "availability",
    ])
  })

  it("partitions the existing validation entries without duplicating rules", () => {
    expect(skillValidationEntriesForStep(validationEntries, "identity")).toEqual(
      validationEntries.slice(0, 2)
    )
    expect(skillValidationEntriesForStep(validationEntries, "instructions")).toEqual([
      validationEntries[2],
    ])
    expect(skillValidationEntriesForStep(validationEntries, "documents")).toEqual([])
    expect(skillValidationEntriesForStep(validationEntries, "availability")).toEqual([])
  })

  it("routes final validation failures to the earliest owning step", () => {
    expect(stepForSkillField("skill-instructions")).toBe("instructions")
    expect(stepForSkillField("skill-name")).toBe("identity")
    expect(stepForSkillField(undefined)).toBe("identity")
  })

  it("keeps safe create defaults out of the create steps", () => {
    expect(initialSkillFormState(null)).toMatchObject({
      isActive: "true",
      isFavorite: "false",
    })
  })
})
