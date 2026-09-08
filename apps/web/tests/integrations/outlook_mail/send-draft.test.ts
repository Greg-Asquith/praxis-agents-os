// apps/web/tests/integrations/outlook_mail/send-draft.test.ts

import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { outlookDraftReview } from "@/integrations/outlook_mail/lib/draft-review"
import { outlookMailSendDraftPresenter } from "@/integrations/outlook_mail/presenters/send-draft"

const args = {
  message: { entity_kind: "outlook_message", mailbox_id: "mailbox", message_id: "draft" },
  _draft: {
    fingerprint: "a".repeat(64),
    subject: "Reviewed subject",
    body: "<p>Reviewed body</p>",
    body_type: "html",
    from: "dana@example.com",
    sender: "dana@example.com",
    to: ["kai@example.com"],
    cc: ["amal@example.com"],
    bcc: ["lee@example.com"],
    reply_to: [],
  },
}

function approval(value: unknown) {
  return renderToStaticMarkup(
    outlookMailSendDraftPresenter.render({
      activity: {
        id: "draft",
        kind: "call",
        name: "outlook_mail_send_draft",
        status: "awaiting_approval",
        args: value,
      },
      compact: false,
      defaultOpen: true,
      live: false,
      providerKey: "outlook_mail",
      approvalDecision: {
        decision: { decision: "pending", edits: {}, message: "" },
        error: null,
        pendingCount: 0,
        submitting: false,
        onDecisionChange: vi.fn(),
        onRetry: vi.fn(),
      },
    })
  )
}

describe("send existing Outlook draft", () => {
  it("shows all reviewed recipients and the message in the shared frame", () => {
    const html = approval(args)
    for (const value of [
      "kai@example.com",
      "amal@example.com",
      "lee@example.com",
      "Reviewed subject",
      "Reviewed body",
    ]) {
      expect(html).toContain(value)
    }
    expect(html).toContain("sandbox=")
    expect(html).not.toContain("textarea")
    expect(html).not.toContain(args._draft.fingerprint)
  })

  it("blocks approval if the snapshot is missing or malformed", () => {
    for (const value of [
      { message: args.message },
      { ...args, _draft: { ...args._draft, bcc: null } },
    ]) {
      expect(outlookDraftReview(value)).toBeNull()
      const html = approval(value)
      expect(html).toContain("The draft could not be reviewed")
      expect(html).toMatch(/disabled[^>]*>Approve/)
    }
  })
})

describe("settled saved-draft identity", () => {
  it.each(["completed", "denied", "failed"] as const)(
    "retains the reviewed subject after %s",
    (status) => {
      for (const label of ["First saved draft", "Second saved draft"]) {
        for (const withSnapshot of [true, false]) {
          const value = {
            message: { ...args.message, label },
            ...(withSnapshot ? { _draft: { ...args._draft, subject: `${label} reviewed` } } : {}),
          }
          const html = renderToStaticMarkup(
            outlookMailSendDraftPresenter.render({
              activity: {
                id: "draft",
                kind: "result",
                name: "outlook_mail_send_draft",
                status,
                args: value,
                result: {
                  results: [
                    {
                      provider_key: "outlook_mail",
                      display_name: "Mailbox",
                      external_id: "mailbox",
                      status: "success",
                      data: {
                        outcome: "applied",
                        message: args.message,
                        web_link: "https://outlook.office.com/mail/",
                      },
                      error_code: null,
                      error_message: null,
                    },
                  ],
                },
              },
              compact: false,
              defaultOpen: true,
              live: false,
              providerKey: "outlook_mail",
            })
          )
          expect(html).toContain(withSnapshot ? `${label} reviewed` : label)
          expect(html).not.toContain(args._draft.fingerprint)
        }
      }
    }
  )
})
