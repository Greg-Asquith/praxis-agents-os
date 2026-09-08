import { use, useState } from "react"

import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import { Button } from "@/components/ui/button"
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from "@/components/ui/popover"
import { OutlookMessageView } from "@/integrations/outlook_mail/components/message-preview"
import type { OutlookMessageReference } from "@/integrations/outlook_mail/lib/write-args"

export function OutlookMessageRecovery({ message }: { message: OutlookMessageReference }) {
  const conversationId = use(ToolConversationContext)
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-3 grid gap-1 text-xs">
      <p>
        <span className="text-muted-foreground">Returned message: </span>
        {message.label}
      </p>
      {conversationId ? (
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger render={<Button className="w-fit" size="sm" variant="outline" />}>
            View returned message
          </PopoverTrigger>
          {open ? (
            <PopoverContent
              centered
              className="max-h-[80vh] w-[min(42rem,calc(100vw-2rem))] overflow-y-auto"
            >
              <PopoverTitle>{message.label}</PopoverTitle>
              <OutlookMessageView
                mailboxId={message.mailboxId}
                messageId={message.messageId}
                fallback={<p>Loading message…</p>}
                errorFallback={<p>Message unavailable. Check Outlook before trying again.</p>}
              />
            </PopoverContent>
          ) : null}
        </Popover>
      ) : (
        <p className="text-muted-foreground">
          Message unavailable. Open this conversation to check it.
        </p>
      )}
    </div>
  )
}
