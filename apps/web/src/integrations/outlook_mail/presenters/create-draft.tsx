// apps/web/src/integrations/outlook_mail/presenters/create-draft.tsx

import { FilePenLineIcon } from "lucide-react"

import { MAIL_OUTCOME_ICONS } from "@/components/tool-ui/message-outcome-icons"
import { OutlookReplyRecipients } from "@/integrations/outlook_mail/components/reply-recipients"
import { outlookDraftDetails, outlookDraftRows } from "@/integrations/outlook_mail/lib/tool-details"
import {
  outlookDraftArgs,
  validateOutlookDraftArgs,
} from "@/integrations/outlook_mail/lib/write-args"
import { defineOutlookWriteVariant } from "@/integrations/outlook_mail/presenters/write-presenter"
import { createIntegrationWritePresenter } from "@/integrations/write-presenter"

export const outlookMailDraftPresenter = createIntegrationWritePresenter({
  variants: {
    outlook_mail_create_draft: defineOutlookWriteVariant({
      copy: {
        check: "Check Drafts in Outlook before trying again.",
        effect: "saved",
        object: "draft",
        verb: "Save",
      },
      details: outlookDraftDetails,
      parseArgs: outlookDraftArgs,
      prompt:
        "The agent wants to save a draft in Outlook. Nothing is sent. A reply draft includes the quoted conversation.",
      renderSummary: (value, _fallback, onFieldEdit, disabled) => (
        <OutlookReplyRecipients
          args={outlookDraftArgs(value)}
          disabled={disabled}
          onFieldEdit={onFieldEdit}
        />
      ),
      validateArgs: validateOutlookDraftArgs,
      view: (args) => ({
        body: args?.body ?? null,
        icons: { ...MAIL_OUTCOME_ICONS, applied: FilePenLineIcon },
        linkLabel: (outcome) =>
          outcome === "unverified" ? "Open in Outlook" : "Open draft in Outlook",
        note: "Nothing was sent.",
        rows: args ? outlookDraftRows(args) : [],
        subject: args?.subject ?? null,
        titles: {
          applied: "Draft saved",
          failed: "Draft not saved",
          unverified: "Draft not confirmed",
        },
      }),
    }),
  },
})
