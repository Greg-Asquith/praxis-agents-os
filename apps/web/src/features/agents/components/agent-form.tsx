// apps/web/src/features/agents/components/agent-form.tsx

import { useMemo, useState, type SyntheticEvent } from "react"

import { FormActionBar } from "@/components/forms/form-action-bar"
import { FormAlerts } from "@/components/forms/form-alerts"
import {
  buildAgentPayload,
  buildModelOptions,
  initialAgentFormState,
  isAgentFormDirty,
  validateAgentFormState,
  type AgentFormState,
} from "@/features/agents/components/agent-form-model"
import { AgentDelegationSection } from "@/features/agents/components/agent-delegation-section"
import { AgentProfileSection } from "@/features/agents/components/agent-profile-section"
import { AgentRuntimeSection } from "@/features/agents/components/agent-runtime-section"
import { AgentSkillsSection } from "@/features/agents/components/agent-skills-section"
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
      cancelTo: "/agents"
      isSubmitting: boolean
      modelCatalog: ModelCatalogResponse
      onSubmit: (payload: AgentCreateRequest) => Promise<void>
    }
  | {
      mode: "edit"
      agent: Agent
      agents: Agent[]
      cancelLabel: string
      cancelTo: "/agents"
      isSubmitting: boolean
      modelCatalog: ModelCatalogResponse
      onChange?: () => void
      onSubmit: (payload: AgentUpdateRequest) => Promise<void>
    }

export function AgentForm(props: AgentFormProps) {
  const agent = props.mode === "edit" ? props.agent : null
  const { data: toolCatalog } = useToolCatalogQuery()
  const { data: skillsData } = useSkillsQuery({ limit: 100 })
  const initialState = useMemo(
    () => initialAgentFormState(agent, toolCatalog.tools),
    [agent, toolCatalog.tools]
  )
  const [state, setState] = useState<AgentFormState>(() => initialState)
  const [formError, setFormError] = useState<string | null>(null)
  const [showValidation, setShowValidation] = useState(false)
  const modelOptions = useMemo(
    () => buildModelOptions(props.modelCatalog, agent),
    [agent, props.modelCatalog]
  )
  const selectedModelOption =
    modelOptions.find((option) => option.value === state.modelSelection) ?? modelOptions[0]
  const isDirty = props.mode === "edit" ? isAgentFormDirty(state, initialState) : true
  const validationEntries = useMemo(
    () => (showValidation ? validateAgentFormState(state, props.mode) : []),
    [props.mode, showValidation, state]
  )
  const fieldErrors = useMemo(() => buildFieldErrors(validationEntries), [validationEntries])

  function setField<K extends keyof AgentFormState>(field: K, value: AgentFormState[K]) {
    if (props.mode === "edit") {
      props.onChange?.()
    }
    setState((current) => ({ ...current, [field]: value }))
  }

  function setToolMode(toolName: string, mode: RuntimeToolMode) {
    if (props.mode === "edit") {
      props.onChange?.()
    }
    setState((current) => ({
      ...current,
      toolModes: { ...current.toolModes, [toolName]: mode },
    }))
  }

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)

    const nextValidationEntries = validateAgentFormState(state, props.mode)
    if (nextValidationEntries.length > 0) {
      setShowValidation(true)
      return
    }

    setShowValidation(false)

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
        errorTitle="Agent not saved"
        validationEntries={validationEntries}
      />

      <AgentProfileSection
        fieldErrors={{
          instructions: fieldErrors["agent-instructions"],
          name: fieldErrors["agent-name"],
        }}
        setField={setField}
        state={state}
      />
      <AgentRuntimeSection
        fieldErrors={{
          maxSteps: fieldErrors["agent-max-steps"],
          modelSelection: fieldErrors["agent-model"],
        }}
        modelOptions={modelOptions}
        selectedModelOption={selectedModelOption}
        setField={setField}
        setToolMode={setToolMode}
        state={state}
        toolCatalog={toolCatalog.tools}
      />
      <AgentDelegationSection
        agents={props.agents}
        allowedAgentIds={state.allowedAgentIds}
        currentAgentId={agent?.id ?? null}
        onAllowedAgentIdsChange={(allowedAgentIds) => {
          setField("allowedAgentIds", allowedAgentIds)
        }}
      />
      <AgentSkillsSection
        setField={setField}
        skillIds={state.skillIds}
        skills={skillsData.skills}
      />

      <FormActionBar
        cancelLabel={props.cancelLabel}
        cancelTo={props.cancelTo}
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
        submitLabel={props.mode === "create" ? "Create Agent" : "Save Changes"}
      />
    </form>
  )
}
