// apps/web/src/features/schedules/components/schedule-form.tsx

import { useId, useMemo, useRef, useState, type SyntheticEvent } from "react"

import { FormAlerts } from "@/components/forms/form-alerts"
import { FormWizard, type FormWizardNavigation } from "@/components/forms/form-wizard"
import type { Agent } from "@/features/agents/types"
import {
  buildSchedulePayload,
  initialScheduleFormState,
  isScheduleFormDirty,
  validateScheduleFormState,
  type ScheduleFormState,
} from "@/features/schedules/components/schedule-form-model"
import {
  SCHEDULE_CREATE_STEPS,
  SCHEDULE_EDIT_STEPS,
  scheduleValidationEntriesForStep,
  stepForScheduleField,
  type ScheduleWizardStepId,
} from "@/features/schedules/components/schedule-form-wizard-config"
import { SchedulePreviewPanel } from "@/features/schedules/components/schedule-preview-panel"
import { ScheduleReviewSection } from "@/features/schedules/components/schedule-review-section"
import { ScheduleRunSection } from "@/features/schedules/components/schedule-run-section"
import { ScheduleTimingSection } from "@/features/schedules/components/schedule-timing-section"
import { useSchedulePreview } from "@/features/schedules/components/use-schedule-preview"
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
      onSubmit: (payload: ScheduleUpdateRequest) => Promise<void>
      schedule: AgentSchedule
    }

export function ScheduleForm(props: ScheduleFormProps) {
  const formId = useId()
  const wizardNavigationRef = useRef<FormWizardNavigation<ScheduleWizardStepId>>(null)
  const schedule = props.mode === "edit" ? props.schedule : null
  const initialState = useMemo(() => initialScheduleFormState(schedule), [schedule])
  const [state, setState] = useState<ScheduleFormState>(() => initialState)
  const [formError, setFormError] = useState<string | null>(null)
  const [validationStep, setValidationStep] = useState<ScheduleWizardStepId | null>(null)
  const fullValidationEntries = useMemo(() => validateScheduleFormState(state), [state])
  const preview = useSchedulePreview(state)
  const isDirty = props.mode === "edit" ? isScheduleFormDirty(state, initialState) : true
  const selectedAgent = props.agents.find((agent) => agent.id === state.agentId) ?? null

  function setField<K extends keyof ScheduleFormState>(field: K, value: ScheduleFormState[K]) {
    setState((current) => ({ ...current, [field]: value }))
  }

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)

    const nextValidationEntries = validateScheduleFormState(state)
    if (nextValidationEntries.length > 0) {
      const earliestStep = stepForScheduleField(nextValidationEntries[0]?.fieldId)
      setValidationStep(earliestStep)
      wizardNavigationRef.current?.goToStep(earliestStep)
      return
    }

    setValidationStep(null)

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

  function validateStep(stepId: ScheduleWizardStepId) {
    const stepValidationEntries = scheduleValidationEntriesForStep(fullValidationEntries, stepId)
    setValidationStep(stepId)
    return stepValidationEntries.length === 0
  }

  return (
    <form
      id={formId}
      noValidate
      onSubmit={(event) => {
        void handleSubmit(event)
      }}
    >
      <FormWizard
        cancelLabel={props.cancelLabel}
        cancelTo="/schedules"
        disableSubmit={props.mode === "edit" && !isDirty}
        isSubmitting={props.isSubmitting}
        navigationRef={wizardNavigationRef}
        pendingLabel={props.mode === "create" ? "Creating" : "Saving"}
        steps={props.mode === "create" ? SCHEDULE_CREATE_STEPS : SCHEDULE_EDIT_STEPS}
        submitLabel={props.mode === "create" ? "Create Schedule" : "Save Changes"}
        validateStep={validateStep}
      >
        {(activeStepId) => {
          const validationEntries =
            validationStep === activeStepId
              ? scheduleValidationEntriesForStep(fullValidationEntries, activeStepId)
              : []
          const fieldErrors = buildFieldErrors(validationEntries)

          return (
            <div className="flex flex-col gap-6">
              <FormAlerts
                error={formError}
                errorTitle="Schedule not saved"
                validationEntries={validationEntries}
              />
              {activeStepId === "run" ? (
                <ScheduleRunSection
                  agents={props.agents}
                  fieldErrors={{
                    agent: fieldErrors["schedule-agent"],
                    name: fieldErrors["schedule-name"],
                    prompt: fieldErrors["schedule-prompt"],
                  }}
                  mode={props.mode}
                  selectedAgent={selectedAgent}
                  setField={setField}
                  state={state}
                />
              ) : null}
              {activeStepId === "timing" ? (
                <>
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
                  <SchedulePreviewPanel preview={preview} />
                </>
              ) : null}
              {activeStepId === "review" ? (
                <ScheduleReviewSection
                  preview={preview}
                  selectedAgent={selectedAgent}
                  setField={setField}
                  state={state}
                />
              ) : null}
            </div>
          )
        }}
      </FormWizard>
    </form>
  )
}
