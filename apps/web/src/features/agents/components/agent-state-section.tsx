// apps/web/src/features/agents/components/agent-state-section.tsx

import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { AgentFormSection } from "@/features/agents/components/agent-form-section"
import { pluralize } from "@/lib/format"

export function AgentStateSection({ skillIds }: { skillIds: string[] }) {
  const skillCount = skillIds.length
  const skillSummary =
    skillCount === 0
      ? "No skills attached"
      : `${String(skillCount)} ${pluralize(skillCount, "skill")} attached`

  return (
    <AgentFormSection
      description="See how many skills are attached to this agent."
      eyebrow="Skills"
      title="Read-only skill summary"
    >
      <FieldGroup>
        <Field>
          <FieldLabel>Skills</FieldLabel>
          <div className="rounded-md border border-dashed p-3">
            <p className="text-sm font-medium">{skillSummary}</p>
            <FieldDescription className="mt-1">
              Skill management is not available in this form yet.
            </FieldDescription>
          </div>
        </Field>
      </FieldGroup>
    </AgentFormSection>
  )
}
