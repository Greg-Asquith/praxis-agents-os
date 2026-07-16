// apps/web/src/features/skills/components/skill-identity-section.tsx

import { FormSection } from "@/components/forms/form-section"
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"

export function SkillIdentitySection({
  description,
  fieldErrors,
  mode,
  name,
  onDescriptionChange,
  onNameChange,
}: {
  description: string
  fieldErrors: Record<string, string>
  mode: "create" | "edit"
  name: string
  onDescriptionChange: (description: string) => void
  onNameChange: (name: string) => void
}) {
  return (
    <FormSection
      description={
        mode === "create"
          ? "Define the compact catalog entry agents see before they activate this skill."
          : "Help agents recognize when this skill is useful."
      }
      eyebrow="Identity"
      title="Skill identity"
    >
      <FieldGroup>
        <Field data-invalid={fieldErrors["skill-name"] ? true : undefined}>
          <FieldLabel htmlFor="skill-name">Name</FieldLabel>
          <Input
            aria-invalid={fieldErrors["skill-name"] ? true : undefined}
            className="scroll-mt-20"
            id="skill-name"
            maxLength={255}
            onChange={(event) => {
              onNameChange(event.currentTarget.value)
            }}
            required
            value={name}
          />
          <FieldDescription>
            {mode === "create"
              ? "Human-readable name for this skill. The agent identifier is generated from it when saved."
              : "A clear name people can recognize in the skill catalog."}
          </FieldDescription>
          <FieldError>{fieldErrors["skill-name"]}</FieldError>
        </Field>

        <Field data-invalid={fieldErrors["skill-description"] ? true : undefined}>
          <FieldLabel htmlFor="skill-description">Description</FieldLabel>
          <Textarea
            aria-invalid={fieldErrors["skill-description"] ? true : undefined}
            className="min-h-28 scroll-mt-20"
            id="skill-description"
            maxLength={1024}
            onChange={(event) => {
              onDescriptionChange(event.currentTarget.value)
            }}
            required
            value={description}
          />
          <FieldDescription>
            {mode === "create"
              ? "Always visible to the agent - it decides when to activate this skill from the name and description alone. Say what the skill does and when to use it."
              : "Tell agents what this skill does and when they should use it."}
          </FieldDescription>
          <FieldError>{fieldErrors["skill-description"]}</FieldError>
        </Field>
      </FieldGroup>
    </FormSection>
  )
}
