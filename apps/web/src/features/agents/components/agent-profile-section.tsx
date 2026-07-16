// apps/web/src/features/agents/components/agent-profile-section.tsx

import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { FormSection } from "@/components/forms/form-section"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import type {
  AgentFormFieldSetter,
  AgentFormState,
} from "@/features/agents/components/agent-form-model"

export function AgentProfileSection({
  fieldErrors,
  setField,
  state,
}: {
  fieldErrors: Record<"instructions" | "name", string | undefined>
  setField: AgentFormFieldSetter
  state: AgentFormState
}) {
  return (
    <FormSection
      description="Name the agent and write the instructions it should follow during workspace runs."
      eyebrow="Identity"
      title="Name, description, and instructions"
    >
      <FieldGroup>
        <Field className="max-w-xl" data-invalid={fieldErrors.name ? true : undefined}>
          <FieldLabel htmlFor="agent-name">Name</FieldLabel>
          <Input
            aria-invalid={fieldErrors.name ? true : undefined}
            className="scroll-mt-20"
            id="agent-name"
            onChange={(event) => {
              setField("name", event.currentTarget.value)
            }}
            required
            value={state.name}
          />
          <FieldError>{fieldErrors.name}</FieldError>
        </Field>

        <Field>
          <FieldLabel htmlFor="agent-description">Description</FieldLabel>
          <Textarea
            className="min-h-20"
            id="agent-description"
            onChange={(event) => {
              setField("description", event.currentTarget.value)
            }}
            value={state.description}
          />
        </Field>

        <Field data-invalid={fieldErrors.instructions ? true : undefined}>
          <FieldLabel htmlFor="agent-instructions">Instructions</FieldLabel>
          <Textarea
            aria-invalid={fieldErrors.instructions ? true : undefined}
            className="min-h-48 scroll-mt-20"
            id="agent-instructions"
            onChange={(event) => {
              setField("instructions", event.currentTarget.value)
            }}
            required
            value={state.instructions}
          />
          <FieldDescription>
            Keep this durable and specific to the agent&apos;s role.
          </FieldDescription>
          <FieldError>{fieldErrors.instructions}</FieldError>
        </Field>
      </FieldGroup>
    </FormSection>
  )
}
