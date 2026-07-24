// apps/web/src/integrations/gmail/components/search-message-row.tsx
import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"

import { MessageDetailSkeleton, MessageListRow } from "@/components/tool-ui/message"
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover"
import { GmailMessageView } from "@/integrations/gmail/components/message-preview"
import { gmailSearchMessageSelectHandler } from "@/integrations/gmail/lib/search-interaction"
import { relativeDateTime } from "@/lib/format"

export type GmailMessageSummary = {
  date: string
  messageId: string
  sender: string
  snippet: string
  subject: string
}

export function GmailSearchMessageRow({
  connectionId,
  message,
}: {
  connectionId: string
  message: GmailMessageSummary
}) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const selectMessage = gmailSearchMessageSelectHandler({
    connectionId,
    messageId: message.messageId,
    onOpen: () => {
      setOpen(true)
    },
    queryClient,
  })

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <MessageListRow
        date={relativeDateTime(message.date)}
        onSelect={selectMessage}
        renderSelect={(control) => <PopoverTrigger render={control} />}
        sender={message.sender}
        snippet={message.snippet}
        subject={message.subject}
      />
      {open ? (
        <PopoverContent
          centered
          className="max-h-[min(42rem,80vh)] w-[min(42rem,calc(100vw-2rem))] overflow-y-auto"
        >
          <PopoverHeader>
            <PopoverTitle>{message.subject || "(No subject)"}</PopoverTitle>
            <PopoverDescription>
              {message.sender || "Unknown sender"} · {relativeDateTime(message.date)}
            </PopoverDescription>
          </PopoverHeader>
          <GmailMessageView
            connectionId={connectionId}
            errorFallback={
              <p className="text-destructive py-4 text-center text-sm">
                This message preview could not be loaded.
              </p>
            }
            fallback={<MessageDetailSkeleton label="Loading full message…" />}
            messageId={message.messageId}
          />
        </PopoverContent>
      ) : null}
    </Popover>
  )
}
