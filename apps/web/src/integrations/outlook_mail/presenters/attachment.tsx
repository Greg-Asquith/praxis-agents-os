// apps/web/src/integrations/outlook_mail/presenters/attachment.tsx

import { OutlookAttachmentView } from "@/integrations/outlook_mail/components/attachment"
import { parseAttachmentContent } from "@/integrations/outlook_mail/lib/attachments"
import { outlookMailProvider } from "@/integrations/outlook_mail/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

export const outlookMailAttachmentPresenter = defineIntegrationReadPresenter(outlookMailProvider, {
  ariaLabel: "Read Outlook Attachment results",
  emptyLabel: "No mailbox returned this attachment.",
  heading: "Read Outlook Attachment",
  parseResult: parseAttachmentContent,
  progressLabel: "Reading attachment…",
  render: (attachment) => <OutlookAttachmentView attachment={attachment} />,
  tool: "outlook_mail_read_attachment",
})
