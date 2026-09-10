// apps/web/tests/integrations/write-copy.test.ts

import { createElement } from "react"
import { describe, expect, it } from "vitest"

import type { IntegrationProviderUi } from "@/integrations/provider-ui"
import { integrationWriteCopy, titleCaseWords } from "@/integrations/write-copy"

const outlook: IntegrationProviderUi = {
  contextLabel: "Mailbox",
  externalLabel: null,
  fallbackDisplayName: "Selected mailbox",
  Logo: (props) => createElement("svg", props),
  name: "Outlook",
  providerKey: "outlook_mail",
}

describe("integration write copy", () => {
  it.each([
    ["Send", "email", "sent", "The email could not be sent."],
    ["Send", "draft", "sent", "The draft could not be sent."],
    ["Forward", "email", "forwarded", "The email could not be forwarded."],
    ["Save", "draft", "saved", "The draft could not be saved."],
    ["Move", "message", "moved", "The message could not be moved."],
    ["Update", "message", "updated", "The message could not be updated."],
    ["Remove", "keywords", "removed", "The keywords could not be removed."],
  ] as const)("uses complete sentences to %s a %s", (verb, object, effect, failure) => {
    const copy = integrationWriteCopy(outlook, { verb, object, effect })
    expect(copy.failedDescription).toBe(failure)
    expect(copy.emptyLabel).toBe(`Nothing was ${effect}.`)
    expect(copy.deniedDescription).toBe(`This request was declined. Nothing was ${effect}.`)
    expect(copy.progressLabel).toBe(`${copy.progressLabel.split(" ")[0] ?? ""} ${object}…`)
    expect(copy.resultFailure).toContain("couldn't confirm")
    expect(copy.unverifiedDescription).toContain(`whether Outlook ${effect} the ${object}`)
    expect(copy.unverifiedDescription).toContain("Check Outlook before taking further action.")
  })

  it("derives headings, titles, and labels from the provider name", () => {
    const copy = integrationWriteCopy(outlook, { verb: "Send", object: "email", effect: "sent" })
    expect(copy.heading).toBe("Send Outlook Email")
    expect(copy.approval).toEqual({
      approveLabel: "Approve & Send",
      label: "Send Outlook Email",
      title: "Review email before sending",
    })
    expect(copy.waitingLabel).toBe("Waiting for approval to send email…")
    expect(copy.resultAriaLabel).toBe("Send Outlook Email results")
    expect(copy.unconfirmedAriaLabel).toBe("Unconfirmed Send Outlook Email")
  })

  it("marks destructive actions and honours a provider check sentence", () => {
    const copy = integrationWriteCopy(outlook, {
      check: "Check Sent Items in Outlook before trying again.",
      destructive: true,
      effect: "removed",
      object: "campaign budgets",
      verb: "Remove",
    })
    expect(copy.approval.title).toBe("Permanently remove campaign budgets")
    expect(copy.malformedDescription).toBe(
      "The system couldn't confirm the campaign budgets outcome. Check Sent Items in Outlook before trying again."
    )
    expect(copy.unverifiedDescription).toContain("Check Sent Items in Outlook before trying again.")
  })

  it("title-cases objects while keeping advertising acronyms", () => {
    expect(titleCaseWords("campaign shared list")).toBe("Campaign Shared List")
    expect(titleCaseWords("target cpa bids")).toBe("Target CPA Bids")
    expect(titleCaseWords("final urls")).toBe("Final URLs")
  })
})
