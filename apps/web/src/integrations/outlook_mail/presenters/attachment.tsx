// apps/web/src/integrations/outlook_mail/presenters/attachment.tsx

import { parseFanOutData } from "@/components/tool-ui/fan-out"
import type { ToolRowPresenter } from "@/integrations/contract"
import { OutlookAttachmentView } from "@/integrations/outlook_mail/components/attachment"
import { OutlookFanOut, OutlookSkeleton } from "@/integrations/outlook_mail/components/fan-out"
import { parseAttachmentContent } from "@/integrations/outlook_mail/lib/attachments"

const TITLE = "Read Outlook Attachment"

export const outlookMailAttachmentPresenter: ToolRowPresenter = {
  key: "outlook-mail-attachment",
  matches: (activity) => activity.name === "outlook_mail_read_attachment",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return <OutlookSkeleton label="Reading attachment…" title={TITLE} />
    }
    const result = parseFanOutData(activity.result, parseAttachmentContent)
    if (!result) {
      return null
    }
    return (
      <OutlookFanOut
        defaultOpen={defaultOpen}
        emptyLabel="No mailbox returned this attachment."
        entries={result.entries}
        title={TITLE}
      >
        {(_entry, index) => {
          const attachment = result.data[index]
          return attachment ? <OutlookAttachmentView attachment={attachment} /> : null
        }}
      </OutlookFanOut>
    )
  },
}
