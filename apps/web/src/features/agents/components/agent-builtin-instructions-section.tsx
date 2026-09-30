// apps/web/src/features/agents/components/agent-builtin-instructions-section.tsx

import { FormSection } from "@/components/forms/form-section"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Textarea } from "@/components/ui/textarea"
import type {
  AgentFormFieldSetter,
  AgentFormState,
} from "@/features/agents/components/agent-form-model"

export function AgentBuiltinInstructionsSection({
  baseInstructions,
  setField,
  state,
}: {
  baseInstructions: string
  setField: AgentFormFieldSetter
  state: AgentFormState
}) {
  return (
    <FormSection
      description="This agent follows instructions that come with the platform. Add anything specific to your workspace, such as your tone of voice or the clients you work with."
      eyebrow="Instructions"
      title="Workspace instructions"
    >
      <FieldGroup>
        <Field>
          <FieldLabel htmlFor="agent-instructions">Workspace instructions</FieldLabel>
          <Textarea
            className="min-h-40 scroll-mt-20"
            id="agent-instructions"
            onChange={(event) => {
              setField("instructions", event.currentTarget.value)
            }}
            value={state.instructions}
          />
          <FieldDescription>Optional. The agent follows these after its own.</FieldDescription>
        </Field>
        <details className="rounded-md border">
          <summary className="hover:bg-muted/50 cursor-pointer px-3 py-2 text-sm font-medium">
            Instructions from the platform
          </summary>
          <pre className="text-muted-foreground max-h-96 overflow-auto border-t px-3 py-2 font-sans text-sm whitespace-pre-wrap">
            {baseInstructions}
          </pre>
        </details>
      </FieldGroup>
    </FormSection>
  )
}
