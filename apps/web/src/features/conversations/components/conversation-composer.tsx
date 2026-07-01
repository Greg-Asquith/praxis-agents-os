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
import type { Agent } from "@/features/agents/types"
import { useConversationWorkspace } from "@/features/conversations/conversation-workspace-context"
import type { PendingUserMessage } from "@/features/conversations/message-parts"
import { getErrorMessage } from "@/lib/api/errors"
import { cn } from "@/lib/utils"

type ConversationComposerProps =
  | {
      mode: "create"
      agents: Agent[]
      conversationId?: never
      disabledReason?: string | null
      compact?: boolean
    }
  | {
      mode: "turn"
      agents?: never
      conversationId: string
      disabledReason?: string | null
      compact?: boolean
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
    <form
      className={cn(
        "bg-background flex flex-col gap-3 rounded-xl border p-3 shadow-sm",
        props.compact && "rounded-lg p-2"
      )}
      onSubmit={handleSubmit}
    >
      <FieldGroup className={cn("gap-3", props.compact && "gap-2")}>
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
                <SelectValue placeholder="Select an agent" />
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
                        {agentSelectLabel(agent)}
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
            className="max-h-52 min-h-24 resize-y"
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

function agentSelectLabel(agent: Agent) {
  if (!agent.slug || agent.slug === agent.name) {
    return agent.name
  }

  return `${agent.name} · ${agent.slug}`
}
