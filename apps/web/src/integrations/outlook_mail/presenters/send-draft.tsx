// apps/web/src/integrations/outlook_mail/presenters/send-draft.tsx

import { ToolApprovalDecisionCard } from "@/components/tool-ui/approval-card"
import type { ToolRowPresenter } from "@/integrations/contract"
import { OutlookDraftReview } from "@/integrations/outlook_mail/components/draft-review"
import { OutlookMailLogo } from "@/integrations/outlook_mail/components/logo"
import { outlookDraftReview } from "@/integrations/outlook_mail/lib/draft-review"
import { outlookMessageReference } from "@/integrations/outlook_mail/lib/write-args"
import {
  defineOutlookWriteVariant,
  MAIL_ICONS,
} from "@/integrations/outlook_mail/presenters/write-presenter"
import { isRecord } from "@/lib/guards"

const PROMPT = "Send the draft as it is saved in Outlook."

const renderOutcome = defineOutlookWriteVariant({
  copy: {
    approveLabel: "Approve & Send",
    check: "Sent Items and Drafts",
    effect: "sent",
    heading: "Send Outlook Draft",
    object: "draft",
    prompt: PROMPT,
    title: "Review draft before sending",
    verb: "send",
  },
  details: (args) => (args ? [{ label: "Source message", value: args.subject }] : []),
  parseArgs: (value: unknown) => {
    const message = isRecord(value) ? outlookMessageReference(value["message"]) : null
    if (!message) return null
    return { message, subject: outlookDraftReview(value)?.subject ?? message.label }
  },
  view: (args) => ({
    body: null,
    icons: MAIL_ICONS,
    linkLabel: () => "Open in Outlook",
    note: "Outlook accepted the existing draft for sending.",
    rows: [],
    subject: args?.subject ?? null,
    titles: { applied: "Draft sent", failed: "Draft not sent", unverified: "Send not confirmed" },
  }),
})

export const outlookMailSendDraftPresenter: ToolRowPresenter = {
  key: "outlook-mail-send-draft",
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
        icon={<OutlookMailLogo className="size-4" />}
        label="Send Outlook Draft"
        title="Review draft before sending"
        prompt={PROMPT}
        toolName={activity.name}
        derivedFromUntrusted={activity.derivedFromUntrusted ?? false}
        taintSources={activity.taintSources ?? []}
        validationError={
          draft ? null : "The draft could not be reviewed. Decline and prepare it again."
        }
      >
        {draft ? <OutlookDraftReview draft={draft} /> : null}
      </ToolApprovalDecisionCard>
    )
  },
}
