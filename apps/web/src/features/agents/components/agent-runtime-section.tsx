// apps/web/src/features/agents/components/agent-runtime-section.tsx

import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field"
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
  RUNTIME_TOOL_MODE_LABELS,
  RUNTIME_TOOL_OPTIONS,
  type RuntimeToolMode,
  type RuntimeToolName,
} from "@/features/agents/runtime-tools"
import {
  THINKING_OPTIONS,
  type AgentFormFieldSetter,
  type AgentFormState,
  type ModelOption,
} from "@/features/agents/components/agent-form-model"

export function AgentRuntimeSection({
  modelOptions,
  selectedModelOption,
  setField,
  setToolMode,
  state,
}: {
  modelOptions: ModelOption[]
  selectedModelOption: ModelOption | undefined
  setField: AgentFormFieldSetter
  setToolMode: (toolName: RuntimeToolName, mode: RuntimeToolMode) => void
  state: AgentFormState
}) {
  const selectedModelIsAzure = state.modelSelection.startsWith("azure:")
  const selectedThinkingOption = THINKING_OPTIONS.find((option) => option.value === state.thinking)

  return (
    <Card>
      <CardHeader>
        <CardTitle>Runtime</CardTitle>
        <CardDescription>Model override, step budget, and tool approval policy.</CardDescription>
      </CardHeader>
      <CardContent>
        <FieldGroup>
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_180px]">
            <Field>
              <FieldLabel htmlFor="agent-model">Model</FieldLabel>
              <Select
                onValueChange={(value) => {
                  setField("modelSelection", value ?? state.modelSelection)
                }}
                value={state.modelSelection}
              >
                <SelectTrigger id="agent-model" className="w-full">
                  <SelectValue placeholder="Use workspace default" />
                </SelectTrigger>
                <SelectContent align="start">
                  <SelectGroup>
                    <SelectLabel>Configured models</SelectLabel>
                    {modelOptions.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
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
              <FieldDescription>{selectedModelOption?.description}</FieldDescription>
            </Field>

            <Field>
              <FieldLabel htmlFor="agent-max-steps">Max steps</FieldLabel>
              <Input
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
            </Field>
          </div>

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
                      <SelectItem key={option.value} value={option.value}>
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

            {selectedModelIsAzure && (
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
            )}
          </div>

          <FieldSet>
            <FieldLegend>Runtime tools</FieldLegend>
            <div className="grid gap-3">
              {RUNTIME_TOOL_OPTIONS.map((tool) => (
                <div
                  className="flex flex-col justify-between gap-3 rounded-lg border p-3 md:flex-row md:items-center"
                  key={tool.name}
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-medium">{tool.label}</p>
                      <Badge variant="outline">{tool.name}</Badge>
                    </div>
                    <p className="text-muted-foreground mt-1 text-sm">{tool.description}</p>
                  </div>
                  <Select
                    onValueChange={(value) => {
                      if (value !== null) {
                        setToolMode(tool.name, value)
                      }
                    }}
                    value={state.toolModes[tool.name]}
                  >
                    <SelectTrigger
                      aria-label={`${tool.label} policy`}
                      className="w-full md:w-36"
                      size="sm"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent align="end">
                      <SelectGroup>
                        {Object.entries(RUNTIME_TOOL_MODE_LABELS).map(([value, label]) => (
                          <SelectItem key={value} value={value}>
                            {label}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                </div>
              ))}
            </div>
            <FieldDescription>
              Approval mode pauses a run and requires a human decision before the tool executes.
            </FieldDescription>
          </FieldSet>
        </FieldGroup>
      </CardContent>
    </Card>
  )
}
