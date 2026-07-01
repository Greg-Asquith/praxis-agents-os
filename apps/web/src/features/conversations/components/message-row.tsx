// apps/web/src/features/conversations/components/message-row.tsx

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
} from "@/features/conversations/message-parts"

type MessageRowProps =
  | {
      message: ParsedConversationMessage
      pendingMessage?: never
      streaming?: boolean
    }
  | {
      message?: never
      pendingMessage: PendingUserMessage
      streaming?: never
    }

export function MessageRow({ message, pendingMessage, streaming = false }: MessageRowProps) {
  if (pendingMessage) {
    return (
      <UserMessageShell createdAt={pendingMessage.createdAt} pending>
        <MessageMarkdown content={pendingMessage.text} tone="user" />
      </UserMessageShell>
    )
  }

  if (message.role === "user") {
    return (
      <UserMessageShell createdAt={message.createdAt}>
        <MessageTextParts message={message} tone="user" />
      </UserMessageShell>
    )
  }

  if (message.role === "assistant") {
    return (
      <AssistantMessageShell createdAt={message.createdAt} streaming={streaming}>
        <MessageContentParts message={message} />
      </AssistantMessageShell>
    )
  }

  if (message.role === "tool") {
    return <ToolMessageRow message={message} />
  }

  return <UnsupportedMessageRow message={message} />
}

export function AssistantDraftRow({
  id,
  text,
  streaming,
}: {
  id: string
  text: string
  streaming: boolean
}) {
  return (
    <AssistantMessageShell createdAt={null} streaming={streaming}>
      <MessageMarkdown content={text || "Working..."} />
      <span className="sr-only">{id}</span>
    </AssistantMessageShell>
  )
}

function MessageContentParts({ message }: { message: ParsedConversationMessage }) {
  return (
    <>
      <MessageTextParts message={message} tone="assistant" />
      <MessageToolActivities message={message} />
      <UnsupportedPartRows message={message} />
    </>
  )
}

function MessageTextParts({
  message,
  tone,
}: {
  message: ParsedConversationMessage
  tone: "assistant" | "user"
}) {
  return (
    <>
      {message.text.map((text, index) => (
        <MessageMarkdown key={`${message.id}:text:${String(index)}`} content={text} tone={tone} />
      ))}
    </>
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
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-2 px-1">
      <MessageToolActivities message={message} />
      {message.text.map((text, index) => (
        <div
          key={`${message.id}:tool-text:${String(index)}`}
          className="text-muted-foreground rounded-lg border px-3 py-2 text-sm"
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
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-2 px-1">
      <div className="text-muted-foreground rounded-lg border border-dashed px-3 py-2 text-sm">
        Unsupported {message.role} message
      </div>
      <MessageContentParts message={message} />
    </div>
  )
}
