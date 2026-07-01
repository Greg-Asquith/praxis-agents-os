// apps/web/src/features/agents/components/agent-form.tsx

import { useMemo, useState, type SyntheticEvent } from "react"

import {
  buildAgentPayload,
  buildModelOptions,
  initialAgentFormState,
  isAgentFormDirty,
  validateAgentFormState,
  type AgentFormState,
  type AgentFormValidationEntry,
} from "@/features/agents/components/agent-form-model"
import { AgentDelegationSection } from "@/features/agents/components/agent-delegation-section"
import { AgentFormShell } from "@/features/agents/components/agent-form-shell"
import { AgentProfileSection } from "@/features/agents/components/agent-profile-section"
import { AgentRuntimeSection } from "@/features/agents/components/agent-runtime-section"
import { AgentStateSection } from "@/features/agents/components/agent-state-section"
import type { RuntimeToolMode, RuntimeToolName } from "@/features/agents/runtime-tools"
import type { Agent, AgentCreateRequest, AgentUpdateRequest } from "@/features/agents/types"
import type { ModelCatalogResponse } from "@/features/models/types"
import { getErrorMessage } from "@/lib/api/errors"

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
  const initialState = useMemo(() => initialAgentFormState(agent), [agent])
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

  function setToolMode(toolName: RuntimeToolName, mode: RuntimeToolMode) {
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
      className="flex flex-col gap-4"
      noValidate
      onSubmit={(event) => {
        void handleSubmit(event)
      }}
    >
      <AgentFormShell
        cancelLabel={props.cancelLabel}
        cancelTo={props.cancelTo}
        formError={formError}
        isDirty={isDirty}
        isSubmitting={props.isSubmitting}
        mode={props.mode}
        pendingLabel={props.mode === "create" ? "Creating" : "Saving"}
        submitLabel={props.mode === "create" ? "Create agent" : "Save changes"}
        validationEntries={validationEntries}
      >
        <AgentProfileSection
          fieldErrors={{
            instructions: fieldErrors["agent-instructions"],
            name: fieldErrors["agent-name"],
            slug: fieldErrors["agent-slug"],
          }}
          mode={props.mode}
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
        />
        <AgentDelegationSection
          agents={props.agents}
          allowedAgentIds={state.allowedAgentIds}
          currentAgentId={agent?.id ?? null}
          onAllowedAgentIdsChange={(allowedAgentIds) => {
            setField("allowedAgentIds", allowedAgentIds)
          }}
        />
        <AgentStateSection skillIds={agent?.skill_ids ?? []} />
      </AgentFormShell>
    </form>
  )
}

function buildFieldErrors(entries: AgentFormValidationEntry[]) {
  return entries.reduce<Record<string, string>>((errors, entry) => {
    errors[entry.fieldId] = entry.message
    return errors
  }, {})
}
