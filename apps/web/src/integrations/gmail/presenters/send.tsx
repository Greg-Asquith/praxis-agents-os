// apps/web/src/integrations/gmail/presenters/send.tsx

import { MessageWriteOutcome, type MessageOutcomeView } from "@/components/tool-ui/message-outcome"
import { MAIL_OUTCOME_ICONS } from "@/components/tool-ui/message-outcome-icons"
import { gmailRecipientRows, gmailSendDetails } from "@/integrations/gmail/lib/tool-details"
import {
  parseGmailSendArgs,
  parseGmailSentMessageId,
  type GmailSendArgs,
} from "@/integrations/gmail/lib/write-args"
import { gmailProvider } from "@/integrations/gmail/provider"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
} from "@/integrations/write-presenter"

export const gmailSendPresenter = createIntegrationWritePresenter({
  variants: {
    gmail_send_message: defineIntegrationWriteVariant<GmailSendArgs, string>(gmailProvider, {
      approval: {
        parseArgs: parseGmailSendArgs,
        prompt: "The agent wants to send this email from the selected mailbox.",
      },
      copy: { effect: "sent", object: "email", verb: "Send" },
      details: gmailSendDetails,
      parseResult: parseGmailSentMessageId,
      renderFailure: (args, description, _result, disposition) => (
        <MessageWriteOutcome
          description={description}
          outcome={disposition === "unconfirmed" ? "unverified" : "failed"}
          url={null}
          view={sentEmailView(args)}
        />
      ),
      renderOutcome: (_messageId, args) => (
        <MessageWriteOutcome
          description={null}
          outcome="applied"
          url={null}
          view={sentEmailView(args)}
        />
      ),
    }),
  },
})

function sentEmailView(args: GmailSendArgs | null): MessageOutcomeView {
  return {
    body: args?.body ?? null,
    icons: MAIL_OUTCOME_ICONS,
    linkLabel: () => "Open in Gmail",
    note: "Gmail accepted the email for sending.",
    rows: args ? gmailRecipientRows(args) : [],
    subject: args?.subject ?? null,
    titles: { applied: "Email sent", failed: "Email not sent", unverified: "Send not confirmed" },
  }
}
