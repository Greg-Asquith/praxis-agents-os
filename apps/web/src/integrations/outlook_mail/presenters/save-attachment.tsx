// apps/web/src/integrations/outlook_mail/presenters/save-attachment.tsx

import { outlookMailProvider } from "@/integrations/outlook_mail/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"
import { parseSavedFile } from "@/integrations/saved-file"
import { SavedFileSummary } from "@/integrations/saved-file-summary"

export const outlookMailSaveAttachmentPresenter = defineIntegrationReadPresenter(
  outlookMailProvider,
  {
    ariaLabel: "Save Attachment to Files results",
    emptyLabel: "No mailbox returned this attachment.",
    heading: "Save Attachment to Files",
    parseResult: parseSavedFile,
    progressLabel: "Saving attachment to Files…",
    render: (file) => <SavedFileSummary file={file} />,
    tool: "outlook_mail_save_attachment",
  }
)
