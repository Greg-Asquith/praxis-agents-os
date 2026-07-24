// apps/web/src/integrations/gmail/presenters/send.tsx

import { ToolApprovalDecisionCard, type ApprovalField } from "@/components/tool-ui/approval-card"
import { parseFanOutData } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import type { ToolRowPresenter } from "@/integrations/contract"
import { GmailLogo } from "@/integrations/gmail/components/logo"
import { GmailSendMessage, sentMessageArgs } from "@/integrations/gmail/components/sent-message"
import { gmailSendDetails } from "@/integrations/gmail/lib/tool-details"
import { GmailToolHeading } from "@/integrations/gmail/components/tool-heading"
import { isRecord } from "@/lib/guards"

const SEND_FIELDS: ApprovalField[] = [
  field("to", "To", "list"),
  field("subject", "Subject", "text", true),
  field("body_text", "Message", "multiline", true),
  field("cc", "Cc", "list", false, true),
  field("bcc", "Bcc", "list", false, true),
]

export const gmailSendPresenter: ToolRowPresenter = {
  handlesApprovals: true,
  key: "gmail-send-message",
  matches: (activity) => activity.name === "gmail_send_message",
  render: ({ activity, approvalDecision, defaultOpen }) => {
    if (approvalDecision) {
      if (!sentMessageArgs(activity.args)) {
        return null
      }
      return (
        <ToolApprovalDecisionCard
          activityId={activity.id}
          approveLabel="Approve & Send"
          args={activity.args}
          controls={approvalDecision}
          fields={SEND_FIELDS}
          icon={<GmailLogo className="size-4" />}
          label="Send Gmail Message"
          prompt="The agent wants to send this email from the selected mailbox."
          title="Review email before sending"
        />
      )
    }
    if (activity.status === "running") {
      return (
        <FanOutSkeleton
          heading={<GmailToolHeading>Send Gmail Message</GmailToolHeading>}
          label="Sending email…"
        />
      )
    }
    if (activity.status === "awaiting_approval") {
      return (
        <FanOutSkeleton
          heading={<GmailToolHeading>Send Gmail Message</GmailToolHeading>}
          label="Waiting for email approval…"
        />
      )
    }
    if (activity.status === "denied") {
      return sendFailure(
        activity.id,
        activity.args,
        "This email was declined and was not sent.",
        defaultOpen
      )
    }
    if (activity.status === "failed" || activity.status === "unknown") {
      return sendFailure(
        activity.id,
        activity.args,
        "The send did not finish. No delivery was confirmed.",
        defaultOpen
      )
    }
    const fanOut = parseFanOutData(activity.result, sentMessageId)
    if (!fanOut) {
      return sendFailure(
        activity.id,
        activity.args,
        "Praxis could not confirm that this email was delivered.",
        defaultOpen
      )
    }
    const { entries } = fanOut
    return (
      <div aria-label="Sent Gmail messages" className="w-full min-w-0">
        <FanOutShell
          contextLabel="Mailbox"
          defaultOpen={defaultOpen}
          details={gmailSendDetails(activity.args)}
          entries={entries}
          emptyLabel="No mailbox sent this message."
          externalLabel="Email"
          heading={<GmailToolHeading>Send Gmail Message</GmailToolHeading>}
        >
          {() => <GmailSendMessage args={activity.args} state="sent" />}
        </FanOutShell>
      </div>
    )
  },
}

function sendFailure(activityId: string, args: unknown, description: string, defaultOpen: boolean) {
  const entries = [
    {
      connectionId: activityId,
      data: null,
      displayName: "Selected mailbox",
      errorMessage: description,
      externalId: "Selected mailbox",
      status: "failed",
    },
  ]
  return (
    <div aria-label="Unsent Gmail Message" className="w-full min-w-0">
      <FanOutShell
        contextLabel="Mailbox"
        defaultOpen={defaultOpen}
        details={gmailSendDetails(args)}
        entries={entries}
        externalLabel="Email"
        heading={<GmailToolHeading>Send Gmail Message</GmailToolHeading>}
        renderFailed={() => (
          <GmailSendMessage args={args} description={description} state="not-sent" />
        )}
      >
        {() => null}
      </FanOutShell>
    </div>
  )
}

function field(
  key: string,
  label: string,
  format: ApprovalField["format"],
  editable = false,
  secondary = false
): ApprovalField {
  return { key, label, format, editable, secondary, options: [], placeholder: "" }
}

function sentMessageId(value: unknown): string | null {
  return isRecord(value) && typeof value["message_id"] === "string" ? value["message_id"] : null
}
