// apps/web/src/features/conversations/components/conversation-composer.tsx

import {
  useId,
  useRef,
  useState,
  type DragEvent,
  type KeyboardEvent,
  type SyntheticEvent,
} from "react"
import { useQueryClient, type QueryClient } from "@tanstack/react-query"
import { ArrowUpIcon, CircleStopIcon, Loader2Icon, PlusIcon, UploadCloudIcon } from "lucide-react"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { AgentIdentityIcon } from "@/features/agents/components/agent-identity-icon"
import { formatAgentModel } from "@/features/agents/components/agent-model-label"
import { agentSelectLabel } from "@/features/agents/components/agent-select-format"
import { AgentSelectItem } from "@/features/agents/components/agent-select-item"
import type { Agent } from "@/features/agents/types"
import {
  chatAttachmentAcceptValue,
  MAX_CHAT_ATTACHMENTS,
  uploadChatAttachment,
  type MessageAttachment,
} from "@/features/conversations/attachments"
import { useCancelAgentRunMutation } from "@/features/conversations/api/cancel-run"
import { useConversationWorkspace } from "@/features/conversations/conversation-workspace-context"
import type { PendingUserMessage } from "@/features/conversations/message-parts"
import { AttachmentChip } from "./attachment-chip"
import { filesQueryKeys } from "@/features/files/api/list-files"
import type { ModelCatalogResponse } from "@/features/models/types"
import { getErrorMessage } from "@/lib/api/errors"
import { cn } from "@/lib/utils"

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
      agent: Agent
      modelCatalog: ModelCatalogResponse
      conversationId: string
      disabledReason?: string | null
    }

export type ComposerAttachment = {
  localId: string
  fileId: string | null
  mediaType: string
  name: string
  sizeBytes: number
  status: "uploading" | "ready"
}

export function ConversationComposer(props: ConversationComposerProps) {
  const queryClient = useQueryClient()
  const cancelRunMutation = useCancelAgentRunMutation()
  const attachmentInputId = useId()
  const attachmentInputRef = useRef<HTMLInputElement | null>(null)
  const dragDepthRef = useRef(0)
  const { addPendingUserMessage, removePendingUserMessage, stream } = useConversationWorkspace()
  const activeAgents =
    props.mode === "create" ? props.agents.filter((agent) => agent.is_active) : []
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null)
  const [prompt, setPrompt] = useState("")
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([])
  const [isDraggingFiles, setIsDraggingFiles] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const promptText = prompt.trim()
  const effectiveSelectedAgentId = selectedAgentId ?? activeAgents[0]?.id ?? ""
  const selectedAgent = activeAgents.find((agent) => agent.id === effectiveSelectedAgentId)
  const composerAgent = props.mode === "create" ? selectedAgent : props.agent
  const selectedModelLabel = composerAgent
    ? formatAgentModel(composerAgent, props.modelCatalog)
    : null
  const isCreateWithoutAgent = props.mode === "create" && activeAgents.length === 0
  const isCurrentStreamBlocking =
    props.mode === "create"
      ? stream.isStreaming
      : stream.isStreaming && stream.conversationId === props.conversationId
  const hasUploadingAttachments = attachments.some(
    (attachment) => attachment.status === "uploading"
  )
  const inputDisabledReason =
    props.disabledReason ??
    (isCreateWithoutAgent ? "No active agents are available." : null) ??
    (isCurrentStreamBlocking ? "The current turn is still running." : null)
  const sendDisabledReason =
    inputDisabledReason ?? (hasUploadingAttachments ? "Files are still uploading." : null)
  const isDisabled =
    Boolean(sendDisabledReason) ||
    isCurrentStreamBlocking ||
    !promptText ||
    (props.mode === "create" && !effectiveSelectedAgentId)
  const canStopStream =
    stream.isStreaming &&
    stream.runId !== null &&
    stream.status === "running" &&
    (props.mode === "create" || stream.conversationId === props.conversationId)

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    void submitMessage()
  }

  async function submitMessage() {
    if (isDisabled || !promptText) {
      return
    }

    const clientMessageId = createClientMessageId()
    const sentAttachments = attachments
    const readyAttachments = sentAttachments
      .filter((attachment) => attachment.status === "ready" && attachment.fileId)
      .map((attachment) => ({
        fileId: attachment.fileId ?? "",
        mediaType: attachment.mediaType,
        name: attachment.name,
        sizeBytes: attachment.sizeBytes,
      }))
    const pendingMessage: PendingUserMessage = {
      attachments: readyAttachments,
      clientMessageId,
      conversationId: props.mode === "turn" ? props.conversationId : stream.conversationId,
      createdAt: new Date().toISOString(),
      text: promptText,
    }

    setError(null)
    setPrompt("")
    setAttachments([])
    addPendingUserMessage(pendingMessage)

    try {
      if (props.mode === "create") {
        await stream.sendFirstMessage({
          agent_id: effectiveSelectedAgentId,
          attachments: readyAttachments.map((attachment) => attachment.fileId),
          client_message_id: clientMessageId,
          user_prompt: promptText,
        })
      } else {
        await stream.sendTurn({
          conversationId: props.conversationId,
          payload: {
            attachments: readyAttachments.map((attachment) => attachment.fileId),
            client_message_id: clientMessageId,
            user_prompt: promptText,
          },
        })
      }
      removePendingUserMessage(clientMessageId)
    } catch (submitError) {
      removePendingUserMessage(clientMessageId)
      setPrompt(promptText)
      setAttachments(sentAttachments)
      setError(getErrorMessage(submitError))
    }
  }

  async function handleStopRun() {
    if (!canStopStream || stream.runId === null) {
      return
    }

    setError(null)
    try {
      await cancelRunMutation.mutateAsync({
        runId: stream.runId,
        conversationId: props.mode === "turn" ? props.conversationId : stream.conversationId,
      })
    } catch (stopError) {
      setError(getErrorMessage(stopError))
    }
  }

  function handleAttachmentFiles(files: FileList | File[] | null) {
    if (!files || files.length === 0) {
      return
    }

    const selectedFiles = Array.from(files)
    if (attachments.length + selectedFiles.length > MAX_CHAT_ATTACHMENTS) {
      setError(`Attach up to ${String(MAX_CHAT_ATTACHMENTS)} files per message.`)
      if (attachmentInputRef.current) {
        attachmentInputRef.current.value = ""
      }
      return
    }

    setError(null)
    selectedFiles.forEach((file) => {
      void uploadAttachment(file)
    })
    if (attachmentInputRef.current) {
      attachmentInputRef.current.value = ""
    }
  }

  async function uploadAttachment(file: File) {
    const localId = createClientMessageId()
    const initialAttachment: ComposerAttachment = {
      fileId: null,
      localId,
      mediaType: file.type || "application/octet-stream",
      name: file.name,
      sizeBytes: file.size,
      status: "uploading",
    }
    setAttachments((current) => [...current, initialAttachment])
    try {
      const uploaded = await uploadChatAttachment(file)
      setAttachments((current) =>
        current.map((attachment) =>
          attachment.localId === localId
            ? composerAttachmentFromUploaded(localId, uploaded)
            : attachment
        )
      )
      void invalidateUploadedFileQueries(queryClient, uploaded.fileId)
    } catch (uploadError) {
      setAttachments((current) => current.filter((attachment) => attachment.localId !== localId))
      setError(getErrorMessage(uploadError))
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault()
      event.currentTarget.form?.requestSubmit()
    }
  }

  function handlePromptDragEnter(event: DragEvent<HTMLDivElement>) {
    if (inputDisabledReason || !isFileDrag(event)) {
      return
    }

    event.preventDefault()
    dragDepthRef.current += 1
    setIsDraggingFiles(true)
  }

  function handlePromptDragLeave(event: DragEvent<HTMLDivElement>) {
    if (!isDraggingFiles && !isFileDrag(event)) {
      return
    }

    event.preventDefault()
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1)
    if (dragDepthRef.current === 0) {
      setIsDraggingFiles(false)
    }
  }

  function handlePromptDragOver(event: DragEvent<HTMLDivElement>) {
    if (!isFileDrag(event)) {
      return
    }

    event.preventDefault()
    event.dataTransfer.dropEffect = inputDisabledReason ? "none" : "copy"
  }

  function handlePromptDrop(event: DragEvent<HTMLDivElement>) {
    if (!isFileDrag(event)) {
      return
    }

    event.preventDefault()
    dragDepthRef.current = 0
    setIsDraggingFiles(false)

    if (inputDisabledReason) {
      return
    }

    handleAttachmentFiles(event.dataTransfer.files)
  }

  return (
    <form className="flex flex-col gap-2" onSubmit={handleSubmit}>
      {error ? (
        <Alert variant="destructive">
          <AlertTitle>{canStopStream ? "Run not stopped" : "Message not sent"}</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <div
        className={cn(
          "bg-card focus-within:border-ring/60 focus-within:ring-ring/20 relative rounded-2xl border shadow-xs transition-[border-color,box-shadow] focus-within:ring-3",
          isDraggingFiles && "border-ring ring-ring/40 ring-3"
        )}
        onDragEnter={handlePromptDragEnter}
        onDragLeave={handlePromptDragLeave}
        onDragOver={handlePromptDragOver}
        onDrop={handlePromptDrop}
      >
        {attachments.length > 0 ? (
          <div className="flex flex-wrap gap-2 px-3 pt-3">
            {attachments.map((attachment) => (
              <AttachmentChip
                attachment={attachment}
                key={attachment.localId}
                onRemove={() => {
                  setAttachments((current) =>
                    current.filter((item) => item.localId !== attachment.localId)
                  )
                }}
              />
            ))}
          </div>
        ) : null}

        <label className="sr-only" htmlFor="conversation-prompt">
          {props.mode === "create" ? "First message" : "Message"}
        </label>
        <Textarea
          id="conversation-prompt"
          aria-description="Enter sends. Shift+Enter adds a line."
          className={cn(
            "max-h-52 min-h-11 resize-none border-0 bg-transparent px-4 py-2.5 shadow-none focus-visible:border-transparent focus-visible:ring-0 dark:bg-transparent",
            inputDisabledReason ? "rounded-t-2xl rounded-b-none" : "rounded-2xl"
          )}
          disabled={Boolean(inputDisabledReason)}
          onChange={(event) => {
            setPrompt(event.currentTarget.value)
          }}
          onKeyDown={handleKeyDown}
          placeholder={
            inputDisabledReason ??
            (props.mode === "create"
              ? "Start with a focused prompt for the selected agent."
              : "Send a follow-up prompt.")
          }
          rows={1}
          value={prompt}
        />

        <div className="flex min-w-0 items-center gap-1 px-2.5 pb-2">
          <input
            accept={chatAttachmentAcceptValue()}
            aria-label="Attach Files"
            className="sr-only"
            id={attachmentInputId}
            multiple
            onChange={(event) => {
              handleAttachmentFiles(event.currentTarget.files)
            }}
            ref={attachmentInputRef}
            type="file"
          />
          <Button
            aria-label="Attach Files"
            disabled={Boolean(inputDisabledReason) || attachments.length >= MAX_CHAT_ATTACHMENTS}
            onClick={() => {
              attachmentInputRef.current?.click()
            }}
            size="icon"
            type="button"
            variant="ghost"
          >
            <PlusIcon className="size-4" />
          </Button>

          {props.mode === "create" ? (
            <Select
              disabled={activeAgents.length === 0 || isCurrentStreamBlocking}
              onValueChange={(value) => {
                setSelectedAgentId(value)
              }}
              value={effectiveSelectedAgentId}
            >
              <SelectTrigger
                aria-label="Agent"
                className="hover:bg-muted max-w-48 gap-1.5 border-0 px-2 shadow-none focus-visible:border-transparent"
                id="conversation-agent"
                size="sm"
              >
                <SelectValue placeholder="Select an agent">
                  {() =>
                    selectedAgent ? (
                      <>
                        <AgentIdentityIcon
                          agentId={selectedAgent.id}
                          decorative
                          name={selectedAgent.name}
                          size="sm"
                        />
                        <span className="truncate">{selectedAgent.name}</span>
                      </>
                    ) : (
                      "No active agents"
                    )
                  }
                </SelectValue>
              </SelectTrigger>
              <SelectContent align="start" className="max-w-[calc(100vw-2rem)] min-w-72">
                <SelectGroup>
                  {activeAgents.length === 0 ? (
                    <SelectItem value="" disabled>
                      No active agents
                    </SelectItem>
                  ) : (
                    activeAgents.map((agent) => {
                      const secondary = formatAgentModel(agent, props.modelCatalog)
                      return (
                        <SelectItem
                          className="cursor-pointer"
                          key={agent.id}
                          label={agentSelectLabel(agent, secondary)}
                          value={agent.id}
                        >
                          <AgentSelectItem agent={agent} secondary={secondary} />
                        </SelectItem>
                      )
                    })
                  )}
                </SelectGroup>
              </SelectContent>
            </Select>
          ) : (
            <div className="flex min-w-0 items-center gap-1.5 px-2 text-sm">
              <AgentIdentityIcon
                agentId={props.agent.id}
                decorative
                name={props.agent.name}
                size="sm"
              />
              <span className="max-w-48 truncate">{props.agent.name}</span>
            </div>
          )}

          <span className="min-w-0 flex-1" />
          {selectedModelLabel ? (
            <span className="text-muted-foreground mr-2 max-w-[40%] truncate text-xs">
              {selectedModelLabel}
            </span>
          ) : null}

          {canStopStream ? (
            <Button
              aria-label="Stop"
              className="rounded-full"
              disabled={cancelRunMutation.isPending}
              onClick={() => {
                void handleStopRun()
              }}
              size="icon"
              title="Stop the Current Run"
              type="button"
              variant="outline"
            >
              {cancelRunMutation.isPending ? (
                <Loader2Icon className="size-4 animate-spin" />
              ) : (
                <CircleStopIcon className="size-4" />
              )}
            </Button>
          ) : (
            <Button
              aria-label="Send"
              className="rounded-full"
              disabled={isDisabled}
              size="icon"
              title="Send Message (Enter)"
              type="submit"
            >
              <ArrowUpIcon className="size-4" />
            </Button>
          )}
        </div>

        {isDraggingFiles ? (
          <div
            aria-hidden="true"
            className="border-ring/70 bg-background/80 text-foreground pointer-events-none absolute inset-0 flex items-center justify-center rounded-2xl border border-dashed backdrop-blur-[1px]"
          >
            <div className="bg-background flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium shadow-sm">
              <UploadCloudIcon className="text-muted-foreground size-4" />
              Drop files to attach
            </div>
          </div>
        ) : null}
      </div>

      <p className="text-muted-foreground text-center text-xs">
        Agents can make mistakes. Review important results.
      </p>
    </form>
  )
}

function isFileDrag(event: DragEvent<HTMLElement>) {
  return Array.from(event.dataTransfer.types).includes("Files")
}

function createClientMessageId() {
  return globalThis.crypto.randomUUID()
}

function composerAttachmentFromUploaded(
  localId: string,
  attachment: MessageAttachment
): ComposerAttachment {
  return {
    fileId: attachment.fileId,
    localId,
    mediaType: attachment.mediaType,
    name: attachment.name ?? attachment.mediaType,
    sizeBytes: attachment.sizeBytes ?? 0,
    status: "ready",
  }
}

async function invalidateUploadedFileQueries(queryClient: QueryClient, fileId: string) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: filesQueryKeys.lists() }),
    queryClient.invalidateQueries({ queryKey: filesQueryKeys.detail(fileId) }),
    queryClient.invalidateQueries({ queryKey: filesQueryKeys.revisions(fileId) }),
  ])
}
