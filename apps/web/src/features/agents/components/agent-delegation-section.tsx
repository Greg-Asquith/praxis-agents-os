// apps/web/src/features/agents/components/agent-delegation-section.tsx

import { useMemo, useState } from "react"
import { PlusIcon, XIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  NO_AGENT_SELECTION,
  type AgentFormState,
} from "@/features/agents/components/agent-form-model"
import { AgentFormSection } from "@/features/agents/components/agent-form-section"
import type { Agent } from "@/features/agents/types"

export function AgentDelegationSection({
  agents,
  allowedAgentIds,
  currentAgentId,
  onAllowedAgentIdsChange,
}: {
  agents: Agent[]
  allowedAgentIds: string[]
  currentAgentId: string | null
  onAllowedAgentIdsChange: (allowedAgentIds: AgentFormState["allowedAgentIds"]) => void
}) {
  const [delegateSelection, setDelegateSelection] = useState(NO_AGENT_SELECTION)
  const allowedAgentIdSet = useMemo(() => new Set(allowedAgentIds), [allowedAgentIds])
  const agentById = useMemo(() => new Map(agents.map((agent) => [agent.id, agent])), [agents])
  const availableDelegateAgents = useMemo(
    () =>
      agents.filter(
        (candidate) =>
          candidate.is_active &&
          candidate.id !== currentAgentId &&
          !allowedAgentIdSet.has(candidate.id)
      ),
    [agents, allowedAgentIdSet, currentAgentId]
  )
  const effectiveDelegateSelection = availableDelegateAgents.some(
    (candidate) => candidate.id === delegateSelection
  )
    ? delegateSelection
    : NO_AGENT_SELECTION
  const selectedDelegateAgents = allowedAgentIds.map((agentId) => ({
    agent: agentById.get(agentId) ?? null,
    id: agentId,
  }))

  function addDelegate() {
    const agentId =
      effectiveDelegateSelection !== NO_AGENT_SELECTION
        ? effectiveDelegateSelection
        : availableDelegateAgents[0]?.id
    if (!agentId) {
      return
    }

    onAllowedAgentIdsChange(
      allowedAgentIds.includes(agentId) ? allowedAgentIds : [...allowedAgentIds, agentId]
    )
    setDelegateSelection(NO_AGENT_SELECTION)
  }

  function removeDelegate(agentId: string) {
    onAllowedAgentIdsChange(allowedAgentIds.filter((value) => value !== agentId))
  }

  return (
    <AgentFormSection
      description="Limit which active agents this agent can call during a run."
      eyebrow="Delegation boundary"
      title="Allowed sub-agents"
    >
      <FieldGroup>
        <Field>
          <FieldLabel htmlFor="agent-delegate">Allowed sub-agent</FieldLabel>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Select
              disabled={availableDelegateAgents.length === 0}
              onValueChange={(value) => {
                setDelegateSelection(value ?? NO_AGENT_SELECTION)
              }}
              value={effectiveDelegateSelection}
            >
              <SelectTrigger id="agent-delegate" className="w-full">
                <SelectValue placeholder="Select an active agent" />
              </SelectTrigger>
              <SelectContent align="start">
                <SelectGroup>
                  <SelectItem value={NO_AGENT_SELECTION} disabled>
                    Select an active agent
                  </SelectItem>
                  {availableDelegateAgents.map((candidate) => (
                    <SelectItem key={candidate.id} value={candidate.id}>
                      <span className="flex min-w-0 flex-col">
                        <span>{candidate.name}</span>
                        <span className="text-muted-foreground text-xs">{candidate.slug}</span>
                      </span>
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            <Button
              disabled={availableDelegateAgents.length === 0}
              onClick={addDelegate}
              type="button"
              variant="outline"
            >
              <PlusIcon data-icon="inline-start" />
              Allow
            </Button>
          </div>
          <FieldDescription>
            Only active agents can be added. An agent cannot delegate to itself.
          </FieldDescription>
        </Field>

        <div className="flex flex-col gap-2">
          {selectedDelegateAgents.length === 0 ? (
            <p className="text-muted-foreground rounded-md border border-dashed p-3 text-sm">
              No sub-agents are allowed.
            </p>
          ) : (
            selectedDelegateAgents.map(({ agent: selectedAgent, id }) => {
              const label = selectedAgent?.name ?? "Unavailable agent"
              const description =
                selectedAgent?.slug ?? "This agent is no longer available in the current list."

              return (
                <div
                  className="flex min-w-0 items-center justify-between gap-3 rounded-md border p-3"
                  key={id}
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{label}</p>
                    <p className="text-muted-foreground truncate text-xs">{description}</p>
                  </div>
                  <Button
                    aria-label={`Remove ${label}`}
                    onClick={() => {
                      removeDelegate(id)
                    }}
                    size="icon-sm"
                    type="button"
                    variant="outline"
                  >
                    <XIcon />
                  </Button>
                </div>
              )
            })
          )}
        </div>
      </FieldGroup>
    </AgentFormSection>
  )
}
