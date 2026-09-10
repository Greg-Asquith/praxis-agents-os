// apps/web/src/integrations/outlook_mail/presenters/send-draft.tsx

import { ToolApprovalDecisionCard } from "@/components/tool-ui/approval-card"
import { MAIL_OUTCOME_ICONS } from "@/components/tool-ui/message-outcome-icons"
import type { ToolRowPresenter } from "@/integrations/contract"
import { OutlookDraftReview } from "@/integrations/outlook_mail/components/draft-review"
import { outlookDraftReview } from "@/integrations/outlook_mail/lib/draft-review"
import { outlookMessageReference } from "@/integrations/outlook_mail/lib/write-args"
import { defineOutlookWriteVariant } from "@/integrations/outlook_mail/presenters/write-presenter"
import { outlookMailProvider } from "@/integrations/outlook_mail/provider"
import { isRecord } from "@/lib/guards"

const PROMPT = "Send the draft as it is saved in Outlook."

const renderOutcome = defineOutlookWriteVariant({
  copy: {
    check: "Check Sent Items and Drafts in Outlook before trying again.",
    effect: "sent",
    object: "draft",
    verb: "Send",
  },
  details: (args) => (args ? [{ label: "Source message", value: args.subject }] : []),
  parseArgs: (value: unknown) => {
    const message = isRecord(value) ? outlookMessageReference(value["message"]) : null
    if (!message) return null
    return { message, subject: outlookDraftReview(value)?.subject ?? message.label }
  },
  prompt: PROMPT,
  view: (args) => ({
    body: null,
    icons: MAIL_OUTCOME_ICONS,
    linkLabel: () => "Open in Outlook",
    note: "Outlook accepted the existing draft for sending.",
    rows: [],
    subject: args?.subject ?? null,
    titles: { applied: "Draft sent", failed: "Draft not sent", unverified: "Send not confirmed" },
  }),
})

// The approval reviews the saved draft snapshot, which the shared field editors cannot show.
export const outlookMailSendDraftPresenter: ToolRowPresenter = {
  key: "outlook_mail_send_draft",
  handlesApprovals: true,
  matches: (activity) => activity.name === "outlook_mail_send_draft",
  render: (context) => {
    const { activity, approvalDecision } = context
    if (!approvalDecision) return renderOutcome(context)
    const draft = outlookDraftReview(activity.args)
    return (
      <ToolApprovalDecisionCard
        activityId={activity.id}
        approveLabel="Approve & Send"
        args={activity.args}
        controls={approvalDecision}
        {...(activity.derivedFromUntrusted === undefined
          ? {}
          : { derivedFromUntrusted: activity.derivedFromUntrusted })}
        {...(activity.taintSources === undefined ? {} : { taintSources: activity.taintSources })}
        icon={<outlookMailProvider.Logo aria-hidden="true" className="size-4" />}
        label="Send Outlook Draft"
        title="Review draft before sending"
        prompt={PROMPT}
        toolName={activity.name}
        validationError={
          draft ? null : "The draft could not be reviewed. Decline and prepare it again."
        }
      >
        {draft ? <OutlookDraftReview draft={draft} /> : null}
      </ToolApprovalDecisionCard>
    )
  },
}
