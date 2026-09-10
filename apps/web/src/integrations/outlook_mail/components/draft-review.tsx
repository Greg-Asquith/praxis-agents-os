// apps/web/src/integrations/outlook_mail/components/draft-review.tsx

import { HtmlContentFrame } from "@/components/tool-ui/html-content-frame"
import { MessageHeaderRows } from "@/components/tool-ui/message"
import type { outlookDraftReview } from "@/integrations/outlook_mail/lib/draft-review"

type DraftReview = NonNullable<ReturnType<typeof outlookDraftReview>>

// Read-only review of a saved draft, laid out like an email header rather than a form.
export function OutlookDraftReview({ draft }: { draft: DraftReview }) {
  const from = draft.sender === draft.from ? draft.from : `${draft.from} (sent by ${draft.sender})`
  const rows = [
    { label: "From", value: from },
    { label: "To", value: draft.to.join(", ") },
    { label: "Cc", value: draft.cc.join(", ") },
    { label: "Bcc", value: draft.bcc.join(", ") },
    { label: "Reply to", value: draft.replyTo.join(", ") },
    { label: "Subject", value: draft.subject || "(No subject)" },
  ].filter((row) => row.value)
  return (
    <div className="grid min-w-0 gap-3">
      <MessageHeaderRows rows={rows} />
      {draft.bodyType === "html" ? (
        <HtmlContentFrame
          className="border-border h-60 rounded-lg border"
          html={draft.body}
          title={draft.subject || "Draft message"}
        />
      ) : (
        <p className="text-sm wrap-break-word whitespace-pre-wrap">{draft.body}</p>
      )}
      <p className="text-muted-foreground text-xs">
        This sends the draft exactly as it is saved in Outlook. To change anything, update the draft
        first, then review it again.
      </p>
    </div>
  )
}
