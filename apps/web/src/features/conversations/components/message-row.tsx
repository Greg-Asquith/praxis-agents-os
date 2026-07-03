// apps/web/src/features/conversations/components/message-row.tsx

import { ChevronRightIcon } from "lucide-react"

import { ToolCallRow } from "@/features/conversations/components/tool-call-row"
import { MessageMarkdown } from "@/features/conversations/components/message-markdown"
import {
  AssistantMessageShell,
  UserMessageShell,
} from "@/features/conversations/components/message-shell"
import { UnsupportedPartRows } from "@/features/conversations/components/unsupported-part-rows"
import type {
  ParsedConversationMessage,
  PendingUserMessage,
  ToolActivity,
} from "@/features/conversations/message-parts"
import type { ChatMessageDraft } from "@/features/conversations/stream/reducer"

type MessageRowProps =
  | {
      assistantLabel?: string
      message: ParsedConversationMessage
      pendingMessage?: never
      streaming?: boolean
    }
  | {
      assistantLabel?: string
      message?: never
      pendingMessage: PendingUserMessage
      streaming?: never
    }

export function MessageRow({
  assistantLabel = "Agent",
  message,
  pendingMessage,
  streaming = false,
}: MessageRowProps) {
  if (pendingMessage) {
    return (
      <UserMessageShell createdAt={pendingMessage.createdAt} pending>
        <MessageMarkdown content={pendingMessage.text} />
      </UserMessageShell>
    )
  }

  if (message.role === "user") {
    return (
      <UserMessageShell createdAt={message.createdAt}>
        <MessageTextParts message={message} />
      </UserMessageShell>
    )
  }

  if (message.role === "assistant") {
    return (
      <AssistantMessageShell
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
  assistantLabel = "Agent",
  isStreaming,
  messages,
  toolActivities,
}: {
  assistantLabel?: string
  isStreaming: boolean
  messages: ChatMessageDraft[]
  toolActivities: ToolActivity[]
}) {
  return (
    <AssistantMessageShell createdAt={null} label={assistantLabel} streaming={isStreaming}>
      {toolActivities.map((activity) => (
        <ToolCallRow key={`${activity.id}:${activity.kind}`} activity={activity} />
      ))}
      {messages.length > 0 ? (
        messages.map((message) => <LiveMessageDraft key={message.id} message={message} />)
      ) : (
        <p className="text-muted-foreground text-sm">Working...</p>
      )}
    </AssistantMessageShell>
  )
}

function LiveMessageDraft({ message }: { message: ChatMessageDraft }) {
  if (message.channel === "thinking") {
    const content = message.text
      ? [message.text]
      : message.status === "streaming"
        ? ["Working..."]
        : []
    return <ThinkingBlock content={content} idPrefix={`${message.id}:thinking`} />
  }

  return (
    <div>
      <MessageMarkdown content={message.text || "Working..."} />
      <span className="sr-only">{message.id}</span>
    </div>
  )
}

function MessageContentParts({ message }: { message: ParsedConversationMessage }) {
  return (
    <>
      <ThinkingParts message={message} />
      <MessageTextParts message={message} />
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
        View Thoughts
      </summary>
      <div className="text-muted-foreground border-border/70 mt-2 ml-1.5 border-l pl-3 italic">
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
      {message.text.map((text, index) => (
        <div
          key={`${message.id}:tool-text:${String(index)}`}
          className="text-muted-foreground bg-muted/50 rounded-lg px-3 py-2 text-sm"
        >
          <MessageMarkdown content={text} />
        </div>
      ))}
      <UnsupportedPartRows message={message} />
    </div>
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
