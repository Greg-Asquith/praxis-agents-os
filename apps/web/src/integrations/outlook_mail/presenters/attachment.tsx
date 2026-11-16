// apps/web/src/integrations/outlook_mail/presenters/attachment.tsx

import { OutlookAttachmentView } from "@/integrations/outlook_mail/components/attachment"
import { parseAttachmentContent } from "@/integrations/outlook_mail/lib/attachments"
import { attachmentReference } from "@/integrations/outlook_mail/lib/messages"
import { outlookMailProvider } from "@/integrations/outlook_mail/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"
import { isRecord } from "@/lib/guards"

export const outlookMailAttachmentPresenter = defineIntegrationReadPresenter(outlookMailProvider, {
  ariaLabel: "Read Outlook Attachment results",
  emptyLabel: "No mailbox returned this attachment.",
  heading: "Read Outlook Attachment",
  parseResult: parseAttachmentContent,
  progressLabel: "Reading attachment…",
  render: (attachment, _entry, args) => (
    <OutlookAttachmentView
      attachment={attachment}
      reference={attachmentReference(isRecord(args) ? args["attachment"] : null)}
    />
  ),
  tool: "outlook_mail_read_attachment",
})
