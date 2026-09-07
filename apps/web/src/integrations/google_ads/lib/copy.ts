// apps/web/src/integrations/google_ads/lib/copy.ts

import { googleAdsTokenLabel } from "@/integrations/google_ads/lib/tokens"

type WriteCopySpec = {
  verb: "Update" | "Create" | "Assign" | "Remove" | "Link" | "Unlink" | "Apply" | "Dismiss" | "Add"
  object: string
  objectPlural?: string
  effect: string
  destructive?: boolean
}

const PROGRESS_VERBS = {
  Update: "Updating",
  Create: "Creating",
  Assign: "Assigning",
  Remove: "Removing",
  Link: "Linking",
  Unlink: "Unlinking",
  Apply: "Applying",
  Dismiss: "Dismissing",
  Add: "Adding",
}

export function approvalCountLine(count: number, noun: string): string {
  return `${String(count)} ${noun}${count === 1 ? "" : "s"}`
}

export function googleAdsWriteCopy(spec: WriteCopySpec) {
  const { verb, object, effect } = spec
  const plural = spec.objectPlural ?? object
  const title = object
    .split(" ")
    .map((word) => googleAdsTokenLabel(word))
    .join(" ")
  const verification = "Check Google Ads before taking further action."
  return {
    heading: `${verb} ${title}`,
    approval: {
      label: `${verb} Google Ads ${title}`,
      title: spec.destructive ? `Permanently ${verb.toLowerCase()} ${object}` : `${verb} ${title}`,
      approveLabel: `Approve & ${verb}`,
    },
    progressLabel: `${PROGRESS_VERBS[verb]} Google Ads ${object}…`,
    waitingLabel: `Waiting for ${object} approval…`,
    deniedDescription: `This ${object} change was declined. Nothing was ${effect}.`,
    failedDescription: `The ${verb.toLowerCase()} did not finish. No ${object} change was confirmed.`,
    emptyLabel: `No Google Ads accounts ${effect} ${plural}.`,
    malformedDescription: `The system couldn't verify this account's ${object} outcomes. ${verification}`,
    resultFailure: `The system couldn't verify the ${object} changes. ${verification}`,
    unverifiedDescription: `The system couldn't verify whether Google Ads ${effect} ${plural}. ${verification}`,
    resultAriaLabel: `Google Ads ${object} results`,
    unconfirmedAriaLabel: `Unconfirmed Google Ads ${object} change`,
  }
}
