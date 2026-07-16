// apps/web/src/features/skills/components/skill-instructions-section.tsx

import { FormSection } from "@/components/forms/form-section"
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Textarea } from "@/components/ui/textarea"

export function SkillInstructionsSection({
  fieldErrors,
  instructions,
  mode,
  onInstructionsChange,
}: {
  fieldErrors: Record<string, string>
  instructions: string
  mode: "create" | "edit"
  onInstructionsChange: (instructions: string) => void
}) {
  return (
    <FormSection
      description={
        mode === "create"
          ? "Write the runbook that loads only after the agent activates this skill."
          : "Give agents the guidance they should follow whenever they use this skill."
      }
      eyebrow="Instructions"
      title="Activation instructions"
    >
      <FieldGroup>
        <Field data-invalid={fieldErrors["skill-instructions"] ? true : undefined}>
          <FieldLabel htmlFor="skill-instructions">Instructions</FieldLabel>
          <Textarea
            aria-invalid={fieldErrors["skill-instructions"] ? true : undefined}
            className="min-h-80 scroll-mt-20"
            id="skill-instructions"
            onChange={(event) => {
              onInstructionsChange(event.currentTarget.value)
            }}
            required
            value={instructions}
          />
          <FieldDescription>
            {mode === "create"
              ? "Loaded only when the agent activates the skill. Keep the description above self-sufficient."
              : "Write the steps, rules, and context the agent needs to complete the work."}
          </FieldDescription>
          <FieldError>{fieldErrors["skill-instructions"]}</FieldError>
        </Field>
      </FieldGroup>
    </FormSection>
  )
}
