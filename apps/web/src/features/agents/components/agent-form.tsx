// apps/web/src/features/agents/components/agent-form.tsx

import { useMemo, useState, type SyntheticEvent } from "react"
import { CheckIcon, SaveIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardFooter } from "@/components/ui/card"
import {
  buildAgentPayload,
  buildModelOptions,
  initialAgentFormState,
  type AgentFormState,
} from "@/features/agents/components/agent-form-model"
import { AgentDelegationSection } from "@/features/agents/components/agent-delegation-section"
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
      isSubmitting: boolean
      modelCatalog: ModelCatalogResponse
      onSubmit: (payload: AgentCreateRequest) => Promise<void>
    }
  | {
      mode: "edit"
      agent: Agent
      agents: Agent[]
      isSubmitting: boolean
      modelCatalog: ModelCatalogResponse
      onSubmit: (payload: AgentUpdateRequest) => Promise<void>
    }

export function AgentForm(props: AgentFormProps) {
  const agent = props.mode === "edit" ? props.agent : null
  const [state, setState] = useState<AgentFormState>(() => initialAgentFormState(agent))
  const [error, setError] = useState<string | null>(null)
  const modelOptions = useMemo(
    () => buildModelOptions(props.modelCatalog, agent),
    [agent, props.modelCatalog]
  )
  const selectedModelOption =
    modelOptions.find((option) => option.value === state.modelSelection) ?? modelOptions[0]

  function setField<K extends keyof AgentFormState>(field: K, value: AgentFormState[K]) {
    setState((current) => ({ ...current, [field]: value }))
  }

  function setToolMode(toolName: RuntimeToolName, mode: RuntimeToolMode) {
    setState((current) => ({
      ...current,
      toolModes: { ...current.toolModes, [toolName]: mode },
    }))
  }

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)

    try {
      if (props.mode === "create") {
        const payload = buildAgentPayload(state, "create")
        if (typeof payload === "string") {
          setError(payload)
          return
        }
        await props.onSubmit(payload)
      } else {
        const payload = buildAgentPayload(state, "edit")
        if (typeof payload === "string") {
          setError(payload)
          return
        }
        await props.onSubmit(payload)
      }
    } catch (submitError) {
      setError(getErrorMessage(submitError))
    }
  }

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        void handleSubmit(event)
      }}
    >
      {error && (
        <Alert variant="destructive">
          <AlertTitle>Agent not saved</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <AgentProfileSection mode={props.mode} setField={setField} state={state} />
      <AgentRuntimeSection
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
      <AgentStateSection setField={setField} skillIds={agent?.skill_ids ?? []} state={state} />

      <Card>
        <CardFooter className="justify-end gap-2">
          <Button disabled={props.isSubmitting} type="submit">
            {props.isSubmitting ? (
              <>
                <SaveIcon data-icon="inline-start" />
                Saving
              </>
            ) : (
              <>
                <CheckIcon data-icon="inline-start" />
                {props.mode === "create" ? "Create agent" : "Save changes"}
              </>
            )}
          </Button>
        </CardFooter>
      </Card>
    </form>
  )
}
