import { describe, expect, it } from "vitest"

import { initialAgentFormState } from "@/features/agents/components/agent-form-model"
import {
  AGENT_CREATE_STEPS,
  AGENT_EDIT_STEPS,
  agentValidationEntriesForStep,
  stepForAgentField,
} from "@/features/agents/components/agent-form-wizard-config"
import type { FormValidationEntry } from "@/lib/forms"

const validationEntries: FormValidationEntry[] = [
  { fieldId: "agent-name", label: "Name", message: "Name is required." },
  {
    fieldId: "agent-instructions",
    label: "Instructions",
    message: "Instructions are required.",
  },
  { fieldId: "agent-model", label: "Model", message: "Model is invalid." },
  { fieldId: "agent-max-steps", label: "Max steps", message: "Max steps are invalid." },
]

describe("agent wizard configuration", () => {
  it("uses four create steps and adds availability when editing", () => {
    expect(AGENT_CREATE_STEPS.map((step) => step.id)).toEqual([
      "profile",
      "model",
      "tools",
      "collaboration",
    ])
    expect(AGENT_EDIT_STEPS.map((step) => step.id)).toEqual([
      "profile",
      "model",
      "tools",
      "collaboration",
      "availability",
    ])
  })

  it("partitions the existing validation entries without duplicating rules", () => {
    expect(agentValidationEntriesForStep(validationEntries, "profile")).toEqual(
      validationEntries.slice(0, 2)
    )
    expect(agentValidationEntriesForStep(validationEntries, "model")).toEqual(
      validationEntries.slice(2)
    )
    expect(agentValidationEntriesForStep(validationEntries, "tools")).toEqual([])
    expect(agentValidationEntriesForStep(validationEntries, "collaboration")).toEqual([])
    expect(agentValidationEntriesForStep(validationEntries, "availability")).toEqual([])
  })

  it("routes final validation failures to their owning step", () => {
    expect(stepForAgentField("agent-model")).toBe("model")
    expect(stepForAgentField("agent-max-steps")).toBe("model")
    expect(stepForAgentField("agent-name")).toBe("profile")
    expect(stepForAgentField("unknown-field")).toBe("profile")
    expect(stepForAgentField(undefined)).toBe("profile")
  })

  it("keeps safe availability defaults out of the create steps", () => {
    expect(initialAgentFormState(null, [])).toMatchObject({
      isActive: "true",
      isFavorite: "false",
    })
    expect(AGENT_CREATE_STEPS.map((step) => step.id)).not.toContain("availability")
  })
})
