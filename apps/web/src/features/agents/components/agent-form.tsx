// apps/web/src/features/agents/components/agent-form.tsx

import { useId, useMemo, useRef, useState, type SyntheticEvent } from "react"

import { FormAlerts } from "@/components/forms/form-alerts"
import { FormWizard, type FormWizardNavigation } from "@/components/forms/form-wizard"
import { AgentAvailabilitySection } from "@/features/agents/components/agent-availability-section"
import { AgentDelegationSection } from "@/features/agents/components/agent-delegation-section"
import {
  buildAgentPayload,
  buildModelOptions,
  initialAgentFormState,
  isAgentFormDirty,
  validateAgentFormState,
  type AgentFormState,
} from "@/features/agents/components/agent-form-model"
import {
  AGENT_CREATE_STEPS,
  AGENT_EDIT_STEPS,
  agentValidationEntriesForStep,
  stepForAgentField,
  type AgentWizardStepId,
} from "@/features/agents/components/agent-form-wizard-config"
import { AgentModelSection } from "@/features/agents/components/agent-model-section"
import { AgentProfileSection } from "@/features/agents/components/agent-profile-section"
import { AgentSkillsSection } from "@/features/agents/components/agent-skills-section"
import { AgentToolsSection } from "@/features/agents/components/agent-tools-section"
import type { RuntimeToolMode } from "@/features/agents/runtime-tools"
import type { Agent, AgentCreateRequest, AgentUpdateRequest } from "@/features/agents/types"
import type { ModelCatalogResponse } from "@/features/models/types"
import { useSkillsQuery } from "@/features/skills/api/list-skills"
import { useToolCatalogQuery } from "@/features/tools/api/list-tool-catalog"
import { getErrorMessage } from "@/lib/api/errors"
import { buildFieldErrors } from "@/lib/forms"

type AgentFormProps =
  | {
      mode: "create"
      agents: Agent[]
      cancelLabel: string
      isSubmitting: boolean
      modelCatalog: ModelCatalogResponse
      onSubmit: (payload: AgentCreateRequest) => Promise<void>
    }
  | {
      mode: "edit"
      agent: Agent
      agents: Agent[]
      cancelLabel: string
      isSubmitting: boolean
      modelCatalog: ModelCatalogResponse
      onSubmit: (payload: AgentUpdateRequest) => Promise<void>
    }

export function AgentForm(props: AgentFormProps) {
  const formId = useId()
  const wizardNavigationRef = useRef<FormWizardNavigation<AgentWizardStepId>>(null)
  const agent = props.mode === "edit" ? props.agent : null
  const { data: toolCatalog } = useToolCatalogQuery()
  const { data: skillsData } = useSkillsQuery({ limit: 100 })
  const initialState = useMemo(
    () => initialAgentFormState(agent, toolCatalog.tools),
    [agent, toolCatalog.tools]
  )
  const [state, setState] = useState<AgentFormState>(() => initialState)
  const [formError, setFormError] = useState<string | null>(null)
  const [validationStep, setValidationStep] = useState<AgentWizardStepId | null>(null)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const modelOptions = useMemo(
    () => buildModelOptions(props.modelCatalog, agent),
    [agent, props.modelCatalog]
  )
  const selectedModelOption =
    modelOptions.find((option) => option.value === state.modelSelection) ?? modelOptions[0]
  const isDirty = props.mode === "edit" ? isAgentFormDirty(state, initialState) : true
  const fullValidationEntries = useMemo(() => validateAgentFormState(state), [state])

  function setField<K extends keyof AgentFormState>(field: K, value: AgentFormState[K]) {
    setState((current) => ({ ...current, [field]: value }))
  }

  function setToolMode(toolName: string, mode: RuntimeToolMode) {
    setState((current) => ({
      ...current,
      toolModes: { ...current.toolModes, [toolName]: mode },
    }))
  }

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)

    const nextValidationEntries = validateAgentFormState(state)
    if (nextValidationEntries.length > 0) {
      const earliestStep = stepForAgentField(nextValidationEntries[0]?.fieldId)
      if (
        earliestStep === "model" &&
        nextValidationEntries.some((entry) => entry.fieldId === "agent-max-steps")
      ) {
        setAdvancedOpen(true)
      }
      setValidationStep(earliestStep)
      wizardNavigationRef.current?.goToStep(earliestStep)
      return
    }

    setValidationStep(null)

    try {
      if (props.mode === "create") {
        const payload = buildAgentPayload(state, "create")
        if (typeof payload === "string") {
          setFormError(payload)
          return
        }
        await props.onSubmit(payload)
      } else {
        const payload = buildAgentPayload(state, "edit")
        if (typeof payload === "string") {
          setFormError(payload)
          return
        }
        await props.onSubmit(payload)
      }
    } catch (submitError) {
      setFormError(getErrorMessage(submitError))
    }
  }

  function validateStep(stepId: AgentWizardStepId) {
    const stepValidationEntries = agentValidationEntriesForStep(fullValidationEntries, stepId)
    if (
      stepId === "model" &&
      stepValidationEntries.some((entry) => entry.fieldId === "agent-max-steps")
    ) {
      setAdvancedOpen(true)
    }
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
        cancelTo="/agents"
        disableSubmit={props.mode === "edit" && !isDirty}
        form={formId}
        isSubmitting={props.isSubmitting}
        navigationRef={wizardNavigationRef}
        pendingLabel={props.mode === "create" ? "Creating" : "Saving"}
        steps={props.mode === "create" ? AGENT_CREATE_STEPS : AGENT_EDIT_STEPS}
        submitLabel={props.mode === "create" ? "Create Agent" : "Save Changes"}
        validateStep={validateStep}
      >
        {(activeStepId) => {
          const validationEntries =
            validationStep === activeStepId
              ? agentValidationEntriesForStep(fullValidationEntries, activeStepId)
              : []
          const fieldErrors = buildFieldErrors(validationEntries)

          return (
            <div className="flex flex-col gap-6">
              <FormAlerts
                error={formError}
                errorTitle="Agent not saved"
                validationEntries={validationEntries}
              />
              {activeStepId === "profile" ? (
                <div className="flex flex-col gap-6">
                  <AgentProfileSection
                    fieldErrors={{
                      instructions: fieldErrors["agent-instructions"],
                      name: fieldErrors["agent-name"],
                    }}
                    setField={setField}
                    state={state}
                  />
                  <AgentSkillsSection
                    setField={setField}
                    skillIds={state.skillIds}
                    skills={skillsData.skills}
                  />
                </div>
              ) : null}
              {activeStepId === "model" ? (
                <AgentModelSection
                  advancedOpen={advancedOpen}
                  fieldErrors={{
                    maxSteps: fieldErrors["agent-max-steps"],
                    modelSelection: fieldErrors["agent-model"],
                  }}
                  modelOptions={modelOptions}
                  onAdvancedOpenChange={setAdvancedOpen}
                  selectedModelLabel={selectedModelOption?.label ?? "Workspace default"}
                  setField={setField}
                  state={state}
                />
              ) : null}
              {activeStepId === "tools" ? (
                <AgentToolsSection
                  onToolModeChange={setToolMode}
                  state={state}
                  toolCatalog={toolCatalog.tools}
                />
              ) : null}
              {activeStepId === "collaboration" ? (
                <AgentDelegationSection
                  agents={props.agents}
                  allowedAgentIds={state.allowedAgentIds}
                  currentAgentId={agent?.id ?? null}
                  onAllowedAgentIdsChange={(allowedAgentIds) => {
                    setField("allowedAgentIds", allowedAgentIds)
                  }}
                />
              ) : null}
              {activeStepId === "availability" && props.mode === "edit" ? (
                <AgentAvailabilitySection
                  isActive={state.isActive}
                  isFavorite={state.isFavorite}
                  onActiveChange={(isActive) => {
                    setField("isActive", isActive)
                  }}
                  onFavoriteChange={(isFavorite) => {
                    setField("isFavorite", isFavorite)
                  }}
                />
              ) : null}
            </div>
          )
        }}
      </FormWizard>
    </form>
  )
}
