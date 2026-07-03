// apps/web/src/features/agents/components/agent-runtime-section.tsx

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
import type { RuntimeToolMode } from "@/features/agents/runtime-tools"
import {
  THINKING_OPTIONS,
  type AgentFormFieldSetter,
  type AgentFormState,
  type ModelOption,
} from "@/features/agents/components/agent-form-model"
import { AgentFormSection } from "@/features/agents/components/agent-form-section"
import { AgentToolsSection } from "@/features/agents/components/agent-tools-section"
import type { ToolCatalogEntry } from "@/features/tools/types"

export function AgentRuntimeSection({
  fieldErrors,
  modelOptions,
  selectedModelOption,
  setField,
  setToolMode,
  state,
  toolCatalog,
}: {
  fieldErrors: Record<"maxSteps" | "modelSelection", string | undefined>
  modelOptions: ModelOption[]
  selectedModelOption: ModelOption | undefined
  setField: AgentFormFieldSetter
  setToolMode: (toolName: string, mode: RuntimeToolMode) => void
  state: AgentFormState
  toolCatalog: ToolCatalogEntry[]
}) {
  const selectedModelIsAzure = state.modelSelection.startsWith("azure:")
  const selectedThinkingOption = THINKING_OPTIONS.find((option) => option.value === state.thinking)

  return (
    <>
      <AgentFormSection
        description="Choose the model override and thinking behavior for this agent."
        eyebrow="Model"
        title="Model selection"
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
                id="agent-model"
                className="w-full scroll-mt-20"
              >
                <SelectValue placeholder="Use workspace default" />
              </SelectTrigger>
              <SelectContent align="start">
                <SelectGroup>
                  <SelectLabel>Configured models</SelectLabel>
                  {modelOptions.map((option) => (
                    <SelectItem key={option.value} label={option.label} value={option.value}>
                      <span className="flex min-w-0 flex-col">
                        <span>{option.label}</span>
                        <span className="text-muted-foreground text-xs">{option.description}</span>
                      </span>
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            <FieldDescription>{selectedModelOption?.description}</FieldDescription>
            <FieldError>{fieldErrors.modelSelection}</FieldError>
          </Field>

          <div className="grid gap-4 md:grid-cols-2">
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
                <SelectTrigger id="agent-thinking" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="start">
                  <SelectGroup>
                    <SelectLabel>Unified thinking</SelectLabel>
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
                {selectedThinkingOption?.description}
                {selectedModelOption?.supportsThinking === false
                  ? " The selected catalog model is not marked as thinking-capable."
                  : ""}
              </FieldDescription>
            </Field>

            {selectedModelIsAzure ? (
              <Field>
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
        </FieldGroup>
      </AgentFormSection>

      <AgentFormSection
        description="Set the run budget and whether this agent appears as active or favored."
        eyebrow="Runtime limits"
        title="Step budget and availability"
      >
        <FieldGroup>
          <div className="grid gap-4 md:grid-cols-3">
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
              <FieldError>{fieldErrors.maxSteps}</FieldError>
            </Field>

            <Field>
              <FieldLabel htmlFor="agent-active">Availability</FieldLabel>
              <Select
                onValueChange={(value) => {
                  setField("isActive", value === "false" ? "false" : "true")
                }}
                value={state.isActive}
              >
                <SelectTrigger id="agent-active" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="start">
                  <SelectGroup>
                    <SelectItem value="true">Active</SelectItem>
                    <SelectItem value="false">Inactive</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>

            <Field>
              <FieldLabel htmlFor="agent-favorite">Favorite</FieldLabel>
              <Select
                onValueChange={(value) => {
                  setField("isFavorite", value === "true" ? "true" : "false")
                }}
                value={state.isFavorite}
              >
                <SelectTrigger id="agent-favorite" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="start">
                  <SelectGroup>
                    <SelectItem value="false">No</SelectItem>
                    <SelectItem value="true">Yes</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
          </div>
        </FieldGroup>
      </AgentFormSection>

      <AgentToolsSection state={state} toolCatalog={toolCatalog} onToolModeChange={setToolMode} />
    </>
  )
}
