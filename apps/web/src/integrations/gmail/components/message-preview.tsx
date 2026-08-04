// apps/web/src/integrations/gmail/components/message-preview.tsx

import type { ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"
import { MailsIcon, TagIcon } from "lucide-react"

import { HtmlContentFrame } from "@/components/tool-ui/html-content-frame"
import { Badge } from "@/components/ui/badge"
import {
  gmailMessagePreviewQueryOptions,
  type GmailMessagePreview,
} from "@/integrations/gmail/api/message-preview"

export function GmailMessageView({
  connectionId,
  errorFallback,
  fallback,
  messageId,
}: {
  connectionId: string
  errorFallback?: ReactNode
  fallback: ReactNode
  messageId: string
}) {
  const preview = useQuery(gmailMessagePreviewQueryOptions(connectionId, messageId))

  // The tool result's plain text renders instantly; the fetched full email
  // replaces it when it arrives, and stays the fallback if the fetch fails.
  if (preview.isPending) {
    return <>{fallback}</>
  }
  if (preview.isError) {
    return <>{errorFallback ?? fallback}</>
  }

  return (
    <div className="grid min-w-0 gap-2">
      <MessageMetaChips meta={preview.data.meta} />
      {preview.data.content_type === "html" ? (
        <HtmlContentFrame
          className="h-120"
          html={preview.data.content}
          title={preview.data.meta.subject?.trim() ? preview.data.meta.subject : "Email message"}
        />
      ) : (
        <p className="text-sm leading-relaxed whitespace-pre-wrap">
          {preview.data.content || "No message content."}
        </p>
      )}
    </div>
  )
}

function MessageMetaChips({ meta }: { meta: GmailMessagePreview["meta"] }) {
  const labels = meta.labels ?? []
  const threadCount = meta.thread_message_count ?? null
  const inThread = threadCount !== null && threadCount > 1

  if (labels.length === 0 && !inThread) {
    return null
  }

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1.5">
      {labels.map((label) => (
        <Badge key={label} variant="outline">
          <TagIcon /> {label}
        </Badge>
      ))}
      {inThread ? (
        <Badge variant="secondary">
          <MailsIcon /> Thread · {String(threadCount)} Messages
        </Badge>
      ) : null}
    </div>
  )
}
