// apps/web/src/features/conversations/components/message-row.tsx

import { ChevronRightIcon } from "lucide-react"

import { ToolCallRow } from "@/features/conversations/components/tool-call-row"
import { MessageMarkdown } from "@/features/conversations/components/message-markdown"
import {
  AssistantMessageShell,
  UserMessageShell,
} from "@/features/conversations/components/message-shell"
import { MessageAttachmentCard } from "@/features/conversations/components/message-attachment-card"
import { UnsupportedPartRows } from "@/features/conversations/components/unsupported-part-rows"
import type { MessageAttachment } from "@/features/conversations/attachments"
import type {
  ParsedConversationMessage,
  PendingUserMessage,
  ToolActivity,
} from "@/features/conversations/message-parts"
import type { ChatMessageDraft } from "@/features/conversations/stream/reducer"

type MessageRowProps =
  | {
      assistantAgentId: string
      assistantLabel?: string
      message: ParsedConversationMessage
      pendingMessage?: never
      streaming?: boolean
    }
  | {
      assistantAgentId: string
      assistantLabel?: string
      message?: never
      pendingMessage: PendingUserMessage
      streaming?: never
    }

export function MessageRow({
  assistantAgentId,
  assistantLabel = "Agent",
  message,
  pendingMessage,
  streaming = false,
}: MessageRowProps) {
  if (pendingMessage) {
    return (
      <UserMessageShell createdAt={pendingMessage.createdAt} pending>
        <MessageMarkdown content={pendingMessage.text} />
        <AttachmentCards attachments={pendingMessage.attachments ?? []} />
      </UserMessageShell>
    )
  }

  if (message.role === "user") {
    return (
      <UserMessageShell createdAt={message.createdAt}>
        <MessageTextParts message={message} />
        <AttachmentCards attachments={message.attachments} />
      </UserMessageShell>
    )
  }

  if (message.role === "assistant") {
    return (
      <AssistantMessageShell
        agentId={assistantAgentId}
        createdAt={message.createdAt}
        label={assistantLabel}
        streaming={streaming}
      >
        <MessageContentParts message={message} />
      </AssistantMessageShell>
    )
  }

  if (message.role === "tool") {
    return <ToolMessageRow message={message} />
  }

  return <UnsupportedMessageRow message={message} />
}

export function AssistantLiveActivityRow({
  assistantAgentId,
  assistantLabel = "Agent",
  isStreaming,
  messages,
  toolActivities,
}: {
  assistantAgentId: string
  assistantLabel?: string
  isStreaming: boolean
  messages: ChatMessageDraft[]
  toolActivities: ToolActivity[]
}) {
  const thinkingContent = liveThinkingContent(messages)
  const textMessages = messages.filter((message) => message.channel !== "thinking")

  return (
    <AssistantMessageShell
      agentId={assistantAgentId}
      createdAt={null}
      label={assistantLabel}
      streaming={isStreaming}
    >
      <ThinkingBlock content={thinkingContent} idPrefix="live-assistant-turn:thinking" />
      {toolActivities.map((activity) => (
        <ToolCallRow key={`${activity.id}:${activity.kind}`} activity={activity} />
      ))}
      {messages.length > 0 ? (
        textMessages.map((message) => <LiveMessageDraft key={message.id} message={message} />)
      ) : (
        <p className="text-muted-foreground animate-pulse text-sm motion-reduce:animate-none">
          Thinking…
        </p>
      )}
    </AssistantMessageShell>
  )
}

export function AssistantTurnRow({
  assistantAgentId,
  assistantLabel = "Agent",
  createdAt,
  messages,
  toolActivities,
}: {
  assistantAgentId: string
  assistantLabel?: string
  createdAt: string
  messages: ParsedConversationMessage[]
  toolActivities: ToolActivity[]
}) {
  const thinkingContent = persistedThinkingContent(messages)

  return (
    <AssistantMessageShell agentId={assistantAgentId} createdAt={createdAt} label={assistantLabel}>
      <ThinkingBlock
        content={thinkingContent}
        idPrefix={`assistant-turn:${messages[0]?.id ?? "unknown"}:thinking`}
      />
      {toolActivities.map((activity, index) => (
        <ToolCallRow key={`${activity.id}:${activity.kind}:${String(index)}`} activity={activity} />
      ))}
      {messages.map((message) => (
        <PersistedAssistantTurnMessage key={message.id} message={message} />
      ))}
    </AssistantMessageShell>
  )
}

function LiveMessageDraft({ message }: { message: ChatMessageDraft }) {
  return (
    <div>
      {message.text ? (
        <MessageMarkdown content={message.text} />
      ) : (
        <p className="text-muted-foreground animate-pulse text-sm motion-reduce:animate-none">
          Thinking…
        </p>
      )}
      <span className="sr-only">{message.id}</span>
    </div>
  )
}

function PersistedAssistantTurnMessage({ message }: { message: ParsedConversationMessage }) {
  if (!hasPersistedTurnContent(message)) {
    return null
  }

  if (message.role === "tool") {
    return <ToolMessageContent message={message} />
  }

  return (
    <>
      <MessageTextParts message={message} />
      <AttachmentCards attachments={message.attachments} />
      <UnsupportedPartRows message={message} />
    </>
  )
}

function MessageContentParts({ message }: { message: ParsedConversationMessage }) {
  return (
    <>
      <ThinkingParts message={message} />
      <MessageTextParts message={message} />
      <AttachmentCards attachments={message.attachments} />
      <MessageToolActivities message={message} />
      <UnsupportedPartRows message={message} />
    </>
  )
}

function MessageTextParts({ message }: { message: ParsedConversationMessage }) {
  return (
    <>
      {message.text.map((text, index) => (
        <MessageMarkdown key={`${message.id}:text:${String(index)}`} content={text} />
      ))}
    </>
  )
}

function AttachmentCards({ attachments }: { attachments: MessageAttachment[] }) {
  if (attachments.length === 0) {
    return null
  }

  return (
    <div className="flex min-w-0 flex-col gap-2">
      {attachments.map((attachment, index) => (
        <MessageAttachmentCard
          key={`${attachment.fileId}:${String(index)}`}
          attachment={attachment}
        />
      ))}
    </div>
  )
}

function ThinkingParts({ message }: { message: ParsedConversationMessage }) {
  if (message.thinking.length === 0) {
    return null
  }

  return <ThinkingBlock content={message.thinking} idPrefix={`${message.id}:thinking`} />
}

function ThinkingBlock({ content, idPrefix }: { content: string[]; idPrefix: string }) {
  if (content.length === 0) {
    return null
  }

  return (
    <details className="group/thinking min-w-0">
      <summary className="text-muted-foreground hover:text-foreground flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium">
        <ChevronRightIcon className="size-3.5 transition-transform group-open/thinking:rotate-90" />
        Show Thinking
      </summary>
      <div className="text-muted-foreground border-border mt-2 ml-1.5 border-l pl-3 text-sm italic">
        {content.map((thought, index) => (
          <MessageMarkdown key={`${idPrefix}:${String(index)}`} content={thought} />
        ))}
      </div>
    </details>
  )
}

function MessageToolActivities({ message }: { message: ParsedConversationMessage }) {
  return (
    <>
      {message.toolActivities.map((activity) => (
        <ToolCallRow key={`${message.id}:${activity.id}:${activity.kind}`} activity={activity} />
      ))}
    </>
  )
}

function ToolMessageRow({ message }: { message: ParsedConversationMessage }) {
  return (
    <div className="flex w-full flex-col gap-2 px-1">
      <MessageToolActivities message={message} />
      <ToolMessageContent message={message} />
    </div>
  )
}

function ToolMessageContent({ message }: { message: ParsedConversationMessage }) {
  return (
    <>
      {message.text.map((text, index) => (
        <div
          key={`${message.id}:tool-text:${String(index)}`}
          className="text-muted-foreground bg-muted/50 rounded-lg px-3 py-2 text-sm"
        >
          <MessageMarkdown content={text} />
        </div>
      ))}
      <UnsupportedPartRows message={message} />
    </>
  )
}

function UnsupportedMessageRow({ message }: { message: ParsedConversationMessage }) {
  return (
    <div className="flex w-full flex-col gap-2 px-1">
      <div className="text-muted-foreground bg-muted/50 rounded-lg px-3 py-2 text-sm">
        Unsupported {message.role} message
      </div>
      <MessageContentParts message={message} />
    </div>
  )
}

function hasPersistedTurnContent(message: ParsedConversationMessage) {
  return (
    message.text.length > 0 || message.attachments.length > 0 || message.unsupportedParts.length > 0
  )
}

function liveThinkingContent(messages: ChatMessageDraft[]) {
  return messages
    .filter((message) => message.channel === "thinking")
    .map((message) => message.text || (message.status === "streaming" ? "Thinking…" : ""))
    .filter((content) => content.length > 0)
}

function persistedThinkingContent(messages: ParsedConversationMessage[]) {
  return messages.flatMap((message) => message.thinking)
}
