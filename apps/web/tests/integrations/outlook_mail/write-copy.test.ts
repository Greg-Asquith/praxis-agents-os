import { describe, expect, it } from "vitest"

import {
  outlookWriteCopy,
  type OutlookWriteCopySpec,
} from "@/integrations/outlook_mail/lib/write-copy"

describe("Outlook action copy", () => {
  it.each<[OutlookWriteCopySpec["verb"], string, string, string, string]>([
    ["send", "email", "sent", "The email could not be sent.", "No email was sent."],
    ["send", "draft", "sent", "The draft could not be sent.", "No draft was sent."],
    ["send", "reply", "sent", "The reply could not be sent.", "No reply was sent."],
    [
      "forward",
      "email",
      "forwarded",
      "The email could not be forwarded.",
      "No email was forwarded.",
    ],
    ["save", "draft", "saved", "The draft could not be saved.", "No draft was saved."],
    ["move", "message", "moved", "The message could not be moved.", "No message was moved."],
    [
      "update",
      "message",
      "updated",
      "The message could not be updated.",
      "No message was updated.",
    ],
  ])("uses complete sentences to %s a %s", (verb, object, effect, failure, empty) => {
    const copy = outlookWriteCopy({
      verb,
      object,
      effect,
      approveLabel: "Approve",
      check: "the message",
      heading: "Action",
      prompt: "Review",
      title: "Review",
    })
    expect(copy.failedDescription).toBe(failure)
    expect(copy.emptyLabel).toBe(empty)
    expect(copy.resultFailure).toContain("could not confirm")
    expect(copy.unverifiedDescription).toContain("couldn't verify")
  })
})
