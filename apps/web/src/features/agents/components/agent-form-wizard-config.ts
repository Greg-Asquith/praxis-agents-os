// apps/web/src/features/agents/components/agent-form-wizard-config.ts

import type { FormWizardStep } from "@/components/forms/form-wizard"
import type { FormValidationEntry } from "@/lib/forms"

export type AgentWizardStepId = "profile" | "model" | "tools" | "collaboration" | "availability"

export const AGENT_CREATE_STEPS = [
  { id: "profile", title: "Who is this agent?" },
  { id: "model", title: "How should it think?" },
  { id: "tools", title: "What can it use?" },
  {
    id: "collaboration",
    optional: true,
    title: "Who can it work with?",
  },
] as const satisfies readonly [
  FormWizardStep<AgentWizardStepId>,
  ...FormWizardStep<AgentWizardStepId>[],
]

export const AGENT_EDIT_STEPS = [
  ...AGENT_CREATE_STEPS,
  { id: "availability", title: "Availability" },
] as const satisfies readonly [
  FormWizardStep<AgentWizardStepId>,
  ...FormWizardStep<AgentWizardStepId>[],
]

const AGENT_STEP_FIELDS: Record<AgentWizardStepId, ReadonlySet<string>> = {
  availability: new Set(),
  collaboration: new Set(),
  model: new Set(["agent-model", "agent-max-steps"]),
  profile: new Set(["agent-name", "agent-instructions"]),
  tools: new Set(),
}

export function agentValidationEntriesForStep(
  entries: readonly FormValidationEntry[],
  stepId: AgentWizardStepId
) {
  const stepFields = AGENT_STEP_FIELDS[stepId]
  return entries.filter((entry) => stepFields.has(entry.fieldId))
}

export function stepForAgentField(fieldId: string | undefined): AgentWizardStepId {
  if (fieldId && AGENT_STEP_FIELDS.model.has(fieldId)) {
    return "model"
  }
  return "profile"
}
