// apps/web/src/features/agents/components/agent-model-section.tsx

import { ChevronDownIcon } from "lucide-react"

import { FormSection } from "@/components/forms/form-section"
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  THINKING_OPTIONS,
  type AgentFormFieldSetter,
  type AgentFormState,
  type ModelOption,
} from "@/features/agents/components/agent-form-model"

export function AgentModelSection({
  advancedOpen,
  fieldErrors,
  modelOptions,
  onAdvancedOpenChange,
  selectedModelLabel,
  setField,
  state,
}: {
  advancedOpen: boolean
  fieldErrors: Record<"maxSteps" | "modelSelection", string | undefined>
  modelOptions: ModelOption[]
  onAdvancedOpenChange: (open: boolean) => void
  selectedModelLabel: string
  setField: AgentFormFieldSetter
  state: AgentFormState
}) {
  const selectedModelIsAzure = state.modelSelection.startsWith("azure:")
  const selectedThinkingOption = THINKING_OPTIONS.find((option) => option.value === state.thinking)

  return (
    <FormSection
      description="Choose the model this agent uses. The workspace default is a good starting point."
      eyebrow="Model"
      title="Model and reasoning"
    >
      <FieldGroup>
        <Field data-invalid={fieldErrors.modelSelection ? true : undefined}>
          <FieldLabel htmlFor="agent-model">Model</FieldLabel>
          <Select
            onValueChange={(value) => {
              setField("modelSelection", value ?? state.modelSelection)
            }}
            value={state.modelSelection}
          >
            <SelectTrigger
              aria-invalid={fieldErrors.modelSelection ? true : undefined}
              className="w-full scroll-mt-20"
              id="agent-model"
            >
              <SelectValue placeholder="Use workspace default">
                {() => selectedModelLabel}
              </SelectValue>
            </SelectTrigger>
            <SelectContent align="start">
              <SelectGroup>
                <SelectLabel>Models</SelectLabel>
                {modelOptions.map((option) => (
                  <SelectItem key={option.value} label={option.label} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          <FieldError>{fieldErrors.modelSelection}</FieldError>
        </Field>

        <details
          className="group rounded-md border"
          onToggle={(event) => {
            onAdvancedOpenChange(event.currentTarget.open)
          }}
          open={advancedOpen}
        >
          <summary className="focus-visible:ring-ring flex cursor-pointer list-none items-center justify-between gap-3 rounded-md px-4 py-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-offset-2 [&::-webkit-details-marker]:hidden">
            <span>
              <span className="font-medium">Advanced</span>
              <span className="text-muted-foreground ml-2">Reasoning and run limits</span>
            </span>
            <ChevronDownIcon
              aria-hidden="true"
              className="text-muted-foreground size-4 transition-transform group-open:rotate-180"
            />
          </summary>
          <div className="grid gap-5 border-t p-4 md:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="agent-thinking">Thinking</FieldLabel>
              <Select
                onValueChange={(value) => {
                  if (value !== null) {
                    setField("thinking", value)
                  }
                }}
                value={state.thinking}
              >
                <SelectTrigger className="w-full" id="agent-thinking">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="start">
                  <SelectGroup>
                    <SelectLabel>Extra reasoning</SelectLabel>
                    {THINKING_OPTIONS.map((option) => (
                      <SelectItem key={option.value} label={option.label} value={option.value}>
                        <span className="flex min-w-0 flex-col">
                          <span>{option.label}</span>
                          <span className="text-muted-foreground text-xs">
                            {option.description}
                          </span>
                        </span>
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              <FieldDescription>
                Control how much extra reasoning the model may use before it responds.
                {selectedThinkingOption ? ` ${selectedThinkingOption.description}` : ""}
              </FieldDescription>
            </Field>

            <Field data-invalid={fieldErrors.maxSteps ? true : undefined}>
              <FieldLabel htmlFor="agent-max-steps">Max steps</FieldLabel>
              <Input
                aria-invalid={fieldErrors.maxSteps ? true : undefined}
                className="scroll-mt-20"
                id="agent-max-steps"
                inputMode="numeric"
                max={100}
                min={1}
                onChange={(event) => {
                  setField("maxSteps", event.currentTarget.value)
                }}
                type="number"
                value={state.maxSteps}
              />
              <FieldDescription>
                The most actions one run may take before it stops.
              </FieldDescription>
              <FieldError>{fieldErrors.maxSteps}</FieldError>
            </Field>

            {selectedModelIsAzure ? (
              <Field className="md:col-span-2">
                <FieldLabel htmlFor="agent-azure-deployment">Azure deployment</FieldLabel>
                <Input
                  id="agent-azure-deployment"
                  onChange={(event) => {
                    setField("azureDeployment", event.currentTarget.value)
                  }}
                  value={state.azureDeployment}
                />
              </Field>
            ) : null}
          </div>
        </details>
      </FieldGroup>
    </FormSection>
  )
}
