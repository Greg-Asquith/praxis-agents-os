// apps/web/src/integrations/outlook_mail/presenters/find-in-attachment.tsx

import { OutlookAttachmentFindView } from "@/integrations/outlook_mail/components/attachment"
import { parseAttachmentMatches } from "@/integrations/outlook_mail/lib/attachments"
import { attachmentReference } from "@/integrations/outlook_mail/lib/messages"
import { outlookMailProvider } from "@/integrations/outlook_mail/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"
import { findQuery } from "@/integrations/text-matches"
import { isRecord } from "@/lib/guards"

export const outlookMailFindInAttachmentPresenter = defineIntegrationReadPresenter(
  outlookMailProvider,
  {
    ariaLabel: "Find in Outlook Attachment results",
    details: (args) => {
      const query = findQuery(args)
      return query === null ? [] : [{ label: "Search", value: query }]
    },
    emptyLabel: "No mailbox returned this attachment.",
    heading: "Find in Outlook Attachment",
    parseResult: parseAttachmentMatches,
    progressLabel: "Searching attachment…",
    render: (found, _entry, args) => (
      <OutlookAttachmentFindView
        found={found}
        query={findQuery(args)}
        reference={attachmentReference(isRecord(args) ? args["attachment"] : null)}
      />
    ),
    tool: "outlook_mail_find_in_attachment",
  }
)
