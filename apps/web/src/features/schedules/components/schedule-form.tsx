// apps/web/src/features/schedules/components/schedule-form.tsx

import { useMemo, useState, type SyntheticEvent } from "react"
import { BotIcon } from "lucide-react"

import { FormActionBar } from "@/components/forms/form-action-bar"
import { FormAlerts } from "@/components/forms/form-alerts"
import { FormSection } from "@/components/forms/form-section"
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
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
import {
  buildSchedulePayload,
  initialScheduleFormState,
  isScheduleFormDirty,
  validateScheduleFormState,
  type ScheduleFormState,
} from "@/features/schedules/components/schedule-form-model"
import { SchedulePreviewPanel } from "@/features/schedules/components/schedule-preview-panel"
import { ScheduleTimingSection } from "@/features/schedules/components/schedule-timing-section"
import type {
  AgentSchedule,
  ScheduleCreateRequest,
  ScheduleUpdateRequest,
} from "@/features/schedules/types"
import { getErrorMessage } from "@/lib/api/errors"
import { buildFieldErrors } from "@/lib/forms"

type ScheduleFormProps =
  | {
      agents: Agent[]
      cancelLabel: string
      isSubmitting: boolean
      mode: "create"
      onSubmit: (payload: ScheduleCreateRequest) => Promise<void>
    }
  | {
      agents: Agent[]
      cancelLabel: string
      isSubmitting: boolean
      mode: "edit"
      onChange?: () => void
      onSubmit: (payload: ScheduleUpdateRequest) => Promise<void>
      schedule: AgentSchedule
    }

export function ScheduleForm(props: ScheduleFormProps) {
  const schedule = props.mode === "edit" ? props.schedule : null
  const initialState = useMemo(() => initialScheduleFormState(schedule), [schedule])
  const [state, setState] = useState<ScheduleFormState>(() => initialState)
  const [formError, setFormError] = useState<string | null>(null)
  const [showValidation, setShowValidation] = useState(false)
  const validationEntries = useMemo(
    () => (showValidation ? validateScheduleFormState(state) : []),
    [showValidation, state]
  )
  const fieldErrors = useMemo(() => buildFieldErrors(validationEntries), [validationEntries])
  const isDirty = props.mode === "edit" ? isScheduleFormDirty(state, initialState) : true
  const selectedAgent = props.agents.find((agent) => agent.id === state.agentId) ?? null

  function setField<K extends keyof ScheduleFormState>(field: K, value: ScheduleFormState[K]) {
    if (props.mode === "edit") {
      props.onChange?.()
    }
    setState((current) => ({ ...current, [field]: value }))
  }

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)

    const nextValidationEntries = validateScheduleFormState(state)
    if (nextValidationEntries.length > 0) {
      setShowValidation(true)
      return
    }

    setShowValidation(false)

    try {
      if (props.mode === "create") {
        const payload = buildSchedulePayload(state, "create")
        if (typeof payload === "string") {
          setFormError(payload)
          return
        }
        await props.onSubmit(payload)
      } else {
        const payload = buildSchedulePayload(state, "edit")
        if (typeof payload === "string") {
          setFormError(payload)
          return
        }
        await props.onSubmit(payload)
      }
    } catch (error) {
      setFormError(getErrorMessage(error))
    }
  }

  return (
    <form
      className="flex flex-col gap-6"
      noValidate
      onSubmit={(event) => {
        void handleSubmit(event)
      }}
    >
      <FormAlerts
        error={formError}
        errorTitle="Schedule not saved"
        validationEntries={validationEntries}
      />

      <FormSection
        description="Choose the agent and prompt that will be used whenever this schedule fires."
        eyebrow="Run"
        icon={<BotIcon className="size-4" />}
        title="Agent and prompt"
      >
        <FieldGroup>
          <Field
            data-disabled={props.mode === "edit" || props.agents.length === 0}
            data-invalid={fieldErrors["schedule-agent"] ? true : undefined}
          >
            <FieldLabel htmlFor="schedule-agent">Agent</FieldLabel>
            <Select
              disabled={props.mode === "edit" || props.agents.length === 0}
              onValueChange={(value) => {
                if (value !== null) {
                  setField("agentId", value)
                }
              }}
              value={state.agentId}
            >
              <SelectTrigger
                aria-invalid={fieldErrors["schedule-agent"] ? true : undefined}
                className="w-full"
                id="schedule-agent"
              >
                <SelectValue placeholder="Select an agent" />
              </SelectTrigger>
              <SelectContent align="start">
                <SelectGroup>
                  <SelectLabel>Workspace agents</SelectLabel>
                  {props.agents.length === 0 ? (
                    <SelectItem value="" disabled>
                      No active agents
                    </SelectItem>
                  ) : (
                    props.agents.map((agent) => (
                      <SelectItem key={agent.id} label={agentSelectLabel(agent)} value={agent.id}>
                        <AgentSelectItem agent={agent} />
                      </SelectItem>
                    ))
                  )}
                  {!selectedAgent && props.mode === "edit" && state.agentId ? (
                    <SelectItem value={state.agentId} disabled>
                      Assigned agent unavailable
                    </SelectItem>
                  ) : null}
                </SelectGroup>
              </SelectContent>
            </Select>
            {props.mode === "edit" ? (
              <FieldDescription>Existing schedules keep their original agent.</FieldDescription>
            ) : null}
            <FieldError>{fieldErrors["schedule-agent"]}</FieldError>
          </Field>

          <Field data-invalid={fieldErrors["schedule-prompt"] ? true : undefined}>
            <FieldLabel htmlFor="schedule-prompt">Prompt</FieldLabel>
            <Textarea
              aria-invalid={fieldErrors["schedule-prompt"] ? true : undefined}
              className="min-h-36 scroll-mt-20"
              id="schedule-prompt"
              onChange={(event) => {
                setField("defaultPrompt", event.currentTarget.value)
              }}
              required
              value={state.defaultPrompt}
            />
            <FieldDescription>
              This prompt starts every run created from the schedule.
            </FieldDescription>
            <FieldError>{fieldErrors["schedule-prompt"]}</FieldError>
          </Field>

          <Field orientation="horizontal">
            <input
              checked={state.isActive}
              className="border-input text-primary focus-visible:ring-ring/50 mt-0.5 size-4 rounded border"
              id="schedule-active"
              onChange={(event) => {
                setField("isActive", event.currentTarget.checked)
              }}
              type="checkbox"
            />
            <div className="flex min-w-0 flex-col gap-1">
              <FieldLabel htmlFor="schedule-active">Active</FieldLabel>
              <FieldDescription>
                Active schedules can be claimed by the worker when their next run is due.
              </FieldDescription>
            </div>
          </Field>

          <Field orientation="horizontal">
            <input
              checked={state.externalWritesAllowed}
              className="border-input text-primary focus-visible:ring-ring/50 mt-0.5 size-4 rounded border"
              id="schedule-external-writes"
              onChange={(event) => {
                setField("externalWritesAllowed", event.currentTarget.checked)
              }}
              type="checkbox"
            />
            <div className="flex min-w-0 flex-col gap-1">
              <FieldLabel htmlFor="schedule-external-writes">Allow external writes</FieldLabel>
              <FieldDescription>
                Use for schedules expected to update connected apps or permanent workspace files.
              </FieldDescription>
            </div>
          </Field>
        </FieldGroup>
      </FormSection>

      <ScheduleTimingSection
        fieldErrors={{
          cron: fieldErrors["schedule-cron"],
          interval: fieldErrors["schedule-interval"],
          once: fieldErrors["schedule-once"],
          timezone: fieldErrors["schedule-timezone"],
        }}
        setField={setField}
        state={state}
      />

      <SchedulePreviewPanel state={state} />

      <FormActionBar
        cancelLabel={props.cancelLabel}
        cancelTo="/schedules"
        disableSubmit={props.isSubmitting || (props.mode === "edit" && !isDirty)}
        isSubmitting={props.isSubmitting}
        pendingLabel={props.mode === "create" ? "Creating" : "Saving"}
        stateMessage={
          props.mode === "edit"
            ? isDirty
              ? "Unsaved changes"
              : "No unsaved changes"
            : "Ready to create when required fields are complete"
        }
        submitLabel={props.mode === "create" ? "Create Schedule" : "Save Changes"}
      />
    </form>
  )
}
