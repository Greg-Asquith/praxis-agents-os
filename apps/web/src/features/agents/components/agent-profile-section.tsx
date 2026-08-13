// apps/web/src/features/agents/components/agent-profile-section.tsx

import type { CSSProperties } from "react"

import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { FormSection } from "@/components/forms/form-section"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  IDENTITY_COLOR_AUTO,
  type AgentFormFieldSetter,
  type AgentFormState,
} from "@/features/agents/components/agent-form-model"
import { AGENT_IDENTITY_COUNT } from "@/lib/agent-identity"
import { cn } from "@/lib/utils"

const identityColorValues = Array.from({ length: AGENT_IDENTITY_COUNT }, (_, index) =>
  String(index + 1)
)

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

        <Field>
          <FieldLabel id="agent-color-label">Color</FieldLabel>
          <div
            aria-labelledby="agent-color-label"
            className="flex flex-wrap items-center gap-2"
            role="group"
          >
            <button
              aria-pressed={state.identityColor === IDENTITY_COLOR_AUTO}
              className={cn(
                "inline-flex h-7 items-center rounded-md border px-3 text-xs font-medium transition-shadow",
                state.identityColor === IDENTITY_COLOR_AUTO
                  ? "ring-ring ring-offset-background ring-2 ring-offset-2"
                  : "hover:bg-muted"
              )}
              onClick={() => {
                setField("identityColor", IDENTITY_COLOR_AUTO)
              }}
              type="button"
            >
              Auto
            </button>
            {identityColorValues.map((value) => (
              <button
                aria-label={`Color ${value}`}
                aria-pressed={state.identityColor === value}
                className={cn(
                  "size-7 shrink-0 rounded-full bg-linear-to-br from-(--agent-color)/95 to-(--agent-color) shadow-xs transition-shadow",
                  state.identityColor === value &&
                    "ring-ring ring-offset-background ring-2 ring-offset-2"
                )}
                key={value}
                onClick={() => {
                  setField("identityColor", value)
                }}
                style={{ "--agent-color": `var(--agent-${value})` } as CSSProperties}
                type="button"
              />
            ))}
          </div>
          <FieldDescription>
            Used for this agent&apos;s icon across the workspace. Auto picks one for you.
          </FieldDescription>
        </Field>
      </FieldGroup>
    </FormSection>
  )
}
