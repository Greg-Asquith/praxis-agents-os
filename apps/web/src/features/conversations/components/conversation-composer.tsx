// apps/web/src/features/conversations/components/conversation-composer.tsx

import { useState, type KeyboardEvent, type SyntheticEvent } from "react"
import { SendIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
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
import { Textarea } from "@/components/ui/textarea"
import { formatAgentModel } from "@/features/agents/components/agent-model-label"
import { agentSelectLabel } from "@/features/agents/components/agent-select-format"
import { AgentSelectItem } from "@/features/agents/components/agent-select-item"
import type { Agent } from "@/features/agents/types"
import { useConversationWorkspace } from "@/features/conversations/conversation-workspace-context"
import type { PendingUserMessage } from "@/features/conversations/message-parts"
import type { ModelCatalogResponse } from "@/features/models/types"
import { getErrorMessage } from "@/lib/api/errors"

type ConversationComposerProps =
  | {
      mode: "create"
      agents: Agent[]
      modelCatalog: ModelCatalogResponse
      conversationId?: never
      disabledReason?: string | null
    }
  | {
      mode: "turn"
      agents?: never
      modelCatalog?: never
      conversationId: string
      disabledReason?: string | null
    }

export function ConversationComposer(props: ConversationComposerProps) {
  const { addPendingUserMessage, removePendingUserMessage, stream } = useConversationWorkspace()
  const activeAgents =
    props.mode === "create" ? props.agents.filter((agent) => agent.is_active) : []
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null)
  const [prompt, setPrompt] = useState("")
  const [error, setError] = useState<string | null>(null)

  const promptText = prompt.trim()
  const effectiveSelectedAgentId = selectedAgentId ?? activeAgents[0]?.id ?? ""
  const selectedAgent = activeAgents.find((agent) => agent.id === effectiveSelectedAgentId) ?? null
  const isCreateWithoutAgent = props.mode === "create" && activeAgents.length === 0
  const isCurrentStreamBlocking =
    props.mode === "create"
      ? stream.isStreaming
      : stream.isStreaming && stream.conversationId === props.conversationId
  const disabledReason =
    props.disabledReason ??
    (isCreateWithoutAgent ? "No active agents are available." : null) ??
    (isCurrentStreamBlocking ? "The current turn is still running." : null)
  const isDisabled =
    Boolean(disabledReason) ||
    isCurrentStreamBlocking ||
    !promptText ||
    (props.mode === "create" && !effectiveSelectedAgentId)

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    void submitMessage()
  }

  async function submitMessage() {
    if (isDisabled || !promptText) {
      return
    }

    const clientMessageId = createClientMessageId()
    const pendingMessage: PendingUserMessage = {
      clientMessageId,
      conversationId: props.mode === "turn" ? props.conversationId : stream.conversationId,
      createdAt: new Date().toISOString(),
      text: promptText,
    }

    setError(null)
    setPrompt("")
    addPendingUserMessage(pendingMessage)

    try {
      if (props.mode === "create") {
        await stream.sendFirstMessage({
          agent_id: effectiveSelectedAgentId,
          client_message_id: clientMessageId,
          user_prompt: promptText,
        })
      } else {
        await stream.sendTurn({
          conversationId: props.conversationId,
          payload: {
            client_message_id: clientMessageId,
            user_prompt: promptText,
          },
        })
      }
    } catch (submitError) {
      removePendingUserMessage(clientMessageId)
      setPrompt(promptText)
      setError(getErrorMessage(submitError))
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault()
      event.currentTarget.form?.requestSubmit()
    }
  }

  return (
    <form className="flex flex-col gap-3" onSubmit={handleSubmit}>
      <FieldGroup className="gap-3">
        {props.mode === "create" && (
          <Field data-disabled={activeAgents.length === 0 || isCurrentStreamBlocking}>
            <FieldLabel htmlFor="conversation-agent">Agent</FieldLabel>
            <Select
              disabled={activeAgents.length === 0 || isCurrentStreamBlocking}
              onValueChange={(value) => {
                setSelectedAgentId(value)
              }}
              value={effectiveSelectedAgentId}
            >
              <SelectTrigger id="conversation-agent" size="sm" className="w-full">
                <SelectValue placeholder="Select an agent">
                  {selectedAgent
                    ? agentSelectLabel(
                        selectedAgent,
                        formatAgentModel(selectedAgent, props.modelCatalog)
                      )
                    : null}
                </SelectValue>
              </SelectTrigger>
              <SelectContent align="start">
                <SelectGroup>
                  {activeAgents.length === 0 ? (
                    <SelectItem value="" disabled>
                      No active agents
                    </SelectItem>
                  ) : (
                    activeAgents.map((agent) => (
                      <SelectItem key={agent.id} value={agent.id}>
                        <AgentSelectItem
                          agent={agent}
                          secondary={formatAgentModel(agent, props.modelCatalog)}
                        />
                      </SelectItem>
                    ))
                  )}
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>
        )}

        {error && (
          <Alert variant="destructive">
            <AlertTitle>Message not sent</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <Field data-disabled={Boolean(disabledReason)}>
          <FieldLabel className="sr-only" htmlFor="conversation-prompt">
            {props.mode === "create" ? "First message" : "Message"}
          </FieldLabel>
          <Textarea
            id="conversation-prompt"
            aria-label={props.mode === "create" ? "First message" : "Message"}
            className="max-h-52 min-h-12 resize-y"
            disabled={Boolean(disabledReason)}
            onChange={(event) => {
              setPrompt(event.currentTarget.value)
            }}
            onKeyDown={handleKeyDown}
            placeholder={
              disabledReason ??
              (props.mode === "create"
                ? "Start with a focused prompt for the selected agent."
                : "Send a follow-up prompt.")
            }
            value={prompt}
          />
        </Field>

        <div className="flex min-w-0 items-center justify-between gap-3">
          <FieldDescription className="truncate text-xs">
            {disabledReason ?? "Enter sends, Shift+Enter adds a line."}
          </FieldDescription>
          <Button disabled={isDisabled} type="submit">
            <SendIcon data-icon="inline-start" />
            Send
          </Button>
        </div>
      </FieldGroup>
    </form>
  )
}

function createClientMessageId() {
  return globalThis.crypto.randomUUID()
}
