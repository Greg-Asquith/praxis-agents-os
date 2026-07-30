// apps/web/src/integrations/gmail/components/message-preview.tsx

import type { ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"
import { MailsIcon, TagIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import {
  gmailMessagePreviewQueryOptions,
  type GmailMessagePreview,
} from "@/integrations/gmail/api/message-preview"
import { buildHtmlFrameDocument } from "@/lib/html-frame-document"

// Server-side sanitization (nh3) is the first layer; this opaque-origin,
// script-less sandbox plus its CSP is the second. Do not add sandbox
// capabilities or allow-same-origin to recover auto-height — the fixed-height
// scroll container is the accepted trade.
const EMAIL_FRAME_CSP =
  "default-src 'none'; img-src data: https: http: cid:; style-src 'unsafe-inline'"
const EMAIL_FRAME_STYLES = [
  "<style>",
  "body{margin:12px;font-family:system-ui,-apple-system,'Segoe UI',sans-serif;",
  "font-size:14px;line-height:1.5;color:#111827;background:#fff;word-break:break-word}",
  "img{max-width:100%;height:auto}",
  "</style>",
].join("")

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
        <iframe
          className="h-120 w-full bg-white"
          sandbox=""
          srcDoc={buildHtmlFrameDocument({
            content: preview.data.content,
            contentSecurityPolicy: EMAIL_FRAME_CSP,
            head: EMAIL_FRAME_STYLES,
          })}
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
