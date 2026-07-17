// apps/web/src/features/schedules/components/schedule-run-section.tsx

import { BotIcon } from "lucide-react"

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
import { Textarea } from "@/components/ui/textarea"
import { agentSelectLabel } from "@/features/agents/components/agent-select-format"
import { AgentSelectItem } from "@/features/agents/components/agent-select-item"
import type { Agent } from "@/features/agents/types"
import type {
  ScheduleFormFieldSetter,
  ScheduleFormState,
} from "@/features/schedules/components/schedule-form-model"

export function ScheduleRunSection({
  agents,
  fieldErrors,
  mode,
  selectedAgent,
  setField,
  state,
}: {
  agents: Agent[]
  fieldErrors: Record<"agent" | "name" | "prompt", string | undefined>
  mode: "create" | "edit"
  selectedAgent: Agent | null
  setField: ScheduleFormFieldSetter
  state: ScheduleFormState
}) {
  return (
    <FormSection
      description="Name the schedule, then choose the agent and message that start each run."
      eyebrow="Run"
      icon={<BotIcon className="size-4" />}
      title="Schedule details"
    >
      <FieldGroup>
        <Field data-invalid={fieldErrors.name ? true : undefined}>
          <FieldLabel htmlFor="schedule-name">Name</FieldLabel>
          <Input
            aria-invalid={fieldErrors.name ? true : undefined}
            id="schedule-name"
            maxLength={255}
            onChange={(event) => {
              setField("name", event.currentTarget.value)
            }}
            placeholder="For example: Weekly account review"
            required
            value={state.name}
          />
          <FieldDescription>
            Use a name that makes this schedule easy to find later.
          </FieldDescription>
          <FieldError>{fieldErrors.name}</FieldError>
        </Field>

        <Field
          data-disabled={mode === "edit" || agents.length === 0}
          data-invalid={fieldErrors.agent ? true : undefined}
        >
          <FieldLabel htmlFor="schedule-agent">Agent</FieldLabel>
          <Select
            disabled={mode === "edit" || agents.length === 0}
            onValueChange={(value) => {
              if (value !== null) {
                setField("agentId", value)
              }
            }}
            value={state.agentId}
          >
            <SelectTrigger
              aria-invalid={fieldErrors.agent ? true : undefined}
              className="w-full"
              id="schedule-agent"
            >
              <SelectValue placeholder="Select an agent" />
            </SelectTrigger>
            <SelectContent align="start">
              <SelectGroup>
                <SelectLabel>Workspace agents</SelectLabel>
                {agents.length === 0 ? (
                  <SelectItem value="" disabled>
                    No active agents
                  </SelectItem>
                ) : (
                  agents.map((agent) => (
                    <SelectItem key={agent.id} label={agentSelectLabel(agent)} value={agent.id}>
                      <AgentSelectItem agent={agent} />
                    </SelectItem>
                  ))
                )}
                {!selectedAgent && mode === "edit" && state.agentId ? (
                  <SelectItem value={state.agentId} disabled>
                    Assigned agent unavailable
                  </SelectItem>
                ) : null}
              </SelectGroup>
            </SelectContent>
          </Select>
          {mode === "edit" ? (
            <FieldDescription>Existing schedules keep their original agent.</FieldDescription>
          ) : null}
          <FieldError>{fieldErrors.agent}</FieldError>
        </Field>

        <Field data-invalid={fieldErrors.prompt ? true : undefined}>
          <FieldLabel htmlFor="schedule-prompt">Prompt</FieldLabel>
          <Textarea
            aria-invalid={fieldErrors.prompt ? true : undefined}
            className="min-h-36 scroll-mt-20"
            id="schedule-prompt"
            onChange={(event) => {
              setField("defaultPrompt", event.currentTarget.value)
            }}
            required
            value={state.defaultPrompt}
          />
          <FieldDescription>
            This message starts every run, exactly as if you had typed it to the agent.
          </FieldDescription>
          <FieldError>{fieldErrors.prompt}</FieldError>
        </Field>
      </FieldGroup>
    </FormSection>
  )
}
