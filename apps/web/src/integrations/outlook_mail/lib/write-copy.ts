// apps/web/src/integrations/outlook_mail/lib/write-copy.ts

export type OutlookWriteCopySpec = {
  approveLabel: string
  /** Where the operator should look in Outlook when the outcome is unconfirmed. */
  check: string
  /** Past tense outcome: sent, forwarded, saved, moved, updated. */
  effect: string
  heading: string
  /** What the tool acts on: email, reply, draft, message. */
  object: string
  prompt: string
  title: string
  verb: keyof typeof PROGRESS
}

const PROGRESS = {
  forward: "Forwarding",
  move: "Moving",
  save: "Saving",
  send: "Sending",
  update: "Updating",
}

export function outlookWriteCopy(spec: OutlookWriteCopySpec) {
  const { check, effect, heading, object, verb } = spec
  const unconfirmed = `The system could not confirm that this ${object} was ${effect}. Check ${check} in Outlook before trying again.`
  return {
    approval: {
      approveLabel: spec.approveLabel,
      label: heading,
      prompt: spec.prompt,
      title: spec.title,
    },
    deniedDescription: `This ${object} was declined and was not ${effect}.`,
    emptyLabel: `No ${object} was ${effect}.`,
    failedDescription: `The ${object} could not be ${effect}.`,
    heading,
    malformedDescription: unconfirmed,
    progressLabel: `${PROGRESS[verb]} ${object}…`,
    resultAriaLabel: `${heading} results`,
    resultFailure: unconfirmed,
    unconfirmedAriaLabel: `Unconfirmed ${heading}`,
    unverifiedDescription: `The system couldn't verify whether Outlook ${effect} this ${object}. Check ${check} in Outlook before trying again.`,
    waitingLabel: `Waiting for approval to ${verb} this ${object}…`,
  }
}
