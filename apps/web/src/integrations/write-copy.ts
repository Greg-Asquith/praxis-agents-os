// apps/web/src/integrations/write-copy.ts

import type { IntegrationProviderUi } from "@/integrations/provider-ui"

const PROGRESS = {
  Add: "Adding",
  Apply: "Applying",
  Assign: "Assigning",
  Create: "Creating",
  Dismiss: "Dismissing",
  Forward: "Forwarding",
  Link: "Linking",
  Move: "Moving",
  Remove: "Removing",
  Save: "Saving",
  Send: "Sending",
  Submit: "Submitting",
  Unlink: "Unlinking",
  Update: "Updating",
} as const

const ACRONYMS = new Set(["API", "CPA", "CPC", "CPM", "CPV", "ID", "ROAS", "URL", "URLS"])

type IntegrationWriteVerb = keyof typeof PROGRESS

export type IntegrationWriteCopySpec = {
  /** Sentence telling the operator where to confirm an unverified outcome. */
  check?: string
  destructive?: boolean
  /** Past participle of the verb, such as "created". */
  effect: string
  /** What the tool acts on, lower case and without an article, such as "campaign budget". */
  object: string
  verb: IntegrationWriteVerb
}

export type IntegrationWriteCopy = {
  approval: { approveLabel: string; label: string; title: string }
  deniedDescription: string
  emptyLabel: string
  failedDescription: string
  heading: string
  malformedDescription: string
  progressLabel: string
  resultAriaLabel: string
  resultFailure: string
  unconfirmedAriaLabel: string
  unverifiedDescription: string
  waitingLabel: string
}

// Every provider's write lifecycle uses these sentences; variants override single strings.
export function integrationWriteCopy(
  provider: IntegrationProviderUi,
  spec: IntegrationWriteCopySpec
): IntegrationWriteCopy {
  const { effect, object, verb } = spec
  const acting = PROGRESS[verb]
  const check = spec.check ?? `Check ${provider.name} before taking further action.`
  const heading = `${verb} ${provider.name} ${titleCaseWords(object)}`
  const unconfirmed = `The system couldn't confirm the ${object} outcome. ${check}`
  return {
    approval: {
      approveLabel: `Approve & ${verb}`,
      label: heading,
      title: spec.destructive
        ? `Permanently ${verb.toLowerCase()} ${object}`
        : `Review ${object} before ${acting.toLowerCase()}`,
    },
    deniedDescription: `This request was declined. Nothing was ${effect}.`,
    emptyLabel: `Nothing was ${effect}.`,
    failedDescription: `The ${object} could not be ${effect}.`,
    heading,
    malformedDescription: unconfirmed,
    progressLabel: `${acting} ${object}…`,
    resultAriaLabel: `${heading} results`,
    resultFailure: unconfirmed,
    unconfirmedAriaLabel: `Unconfirmed ${heading}`,
    unverifiedDescription: `The system couldn't verify whether ${provider.name} ${effect} the ${object}. ${check}`,
    waitingLabel: `Waiting for approval to ${verb.toLowerCase()} ${object}…`,
  }
}

export function titleCaseWords(value: string): string {
  return value
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => {
      const upper = word.toUpperCase()
      return ACRONYMS.has(upper)
        ? upper.replace(/S$/, (suffix) => (upper === "URLS" ? "s" : suffix))
        : `${word.charAt(0).toUpperCase()}${word.slice(1)}`
    })
    .join(" ")
}
