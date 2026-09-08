// apps/web/src/integrations/outlook_mail/presenters/create-draft.tsx

import { FilePenLineIcon } from "lucide-react"

import { OutlookReplyRecipients } from "@/integrations/outlook_mail/components/reply-recipients"

import { outlookDraftDetails, outlookDraftRows } from "@/integrations/outlook_mail/lib/tool-details"
import {
  outlookDraftArgs,
  validateOutlookDraftArgs,
} from "@/integrations/outlook_mail/lib/write-args"
import {
  createOutlookWritePresenter,
  defineOutlookWriteVariant,
  MAIL_ICONS,
} from "@/integrations/outlook_mail/presenters/write-presenter"

export const outlookMailDraftPresenter = createOutlookWritePresenter({
  key: "outlook-mail-create-draft",
  variants: {
    outlook_mail_create_draft: defineOutlookWriteVariant({
      copy: {
        approveLabel: "Approve & Save",
        check: "Drafts",
        effect: "saved",
        heading: "Save Outlook Draft",
        object: "draft",
        prompt:
          "The agent wants to save a draft in Outlook. Nothing is sent. A reply draft includes the quoted conversation.",
        title: "Review draft before saving",
        verb: "save",
      },
      details: outlookDraftDetails,
      parseArgs: outlookDraftArgs,
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
        icons: { ...MAIL_ICONS, applied: FilePenLineIcon },
        linkLabel: () => "Open draft in Outlook",
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
