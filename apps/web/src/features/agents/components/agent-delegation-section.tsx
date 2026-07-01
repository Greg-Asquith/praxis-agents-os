// apps/web/src/features/agents/components/agent-delegation-section.tsx

import { useState } from "react"
import { PlusIcon, XIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
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
  const availableDelegateAgents = agents.filter(
    (candidate) =>
      candidate.is_active &&
      candidate.id !== currentAgentId &&
      !allowedAgentIds.includes(candidate.id)
  )
  const effectiveDelegateSelection = availableDelegateAgents.some(
    (candidate) => candidate.id === delegateSelection
  )
    ? delegateSelection
    : NO_AGENT_SELECTION
  const selectedDelegateAgents = allowedAgentIds.map((agentId) => ({
    agent: agents.find((candidate) => candidate.id === agentId) ?? null,
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
    <Card>
      <CardHeader>
        <CardTitle>Delegation</CardTitle>
        <CardDescription>Limit which active agents this agent may call as sub-agents.</CardDescription>
      </CardHeader>
      <CardContent>
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
                        {candidate.name} ({candidate.slug})
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
              <p className="text-muted-foreground rounded-lg border border-dashed p-3 text-sm">
                No sub-agents are allowed.
              </p>
            ) : (
              selectedDelegateAgents.map(({ agent: selectedAgent, id }) => (
                <div
                  className="flex min-w-0 items-center justify-between gap-3 rounded-lg border p-3"
                  key={id}
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{selectedAgent?.name ?? id}</p>
                    <p className="text-muted-foreground truncate text-xs">
                      {selectedAgent?.slug ?? "Agent not present in the current list"}
                    </p>
                  </div>
                  <Button
                    aria-label={`Remove ${selectedAgent?.name ?? id}`}
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
              ))
            )}
          </div>
        </FieldGroup>
      </CardContent>
    </Card>
  )
}
