import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import type { ToolActivity } from "@/features/conversations/message-parts"
import type { ToolRowPresenter } from "@/integrations/contract"
import { outlookWriteResult } from "@/integrations/outlook_mail/lib/write-results"
import { outlookMailDraftPresenter } from "@/integrations/outlook_mail/presenters/create-draft"
import { outlookMailForwardPresenter } from "@/integrations/outlook_mail/presenters/forward-message"
import { outlookMailMovePresenter } from "@/integrations/outlook_mail/presenters/move-message"
import { outlookMailReplyPresenter } from "@/integrations/outlook_mail/presenters/reply-to-message"
import { outlookMailSendPresenter } from "@/integrations/outlook_mail/presenters/send-message"
import { outlookMailUpdatePresenter } from "@/integrations/outlook_mail/presenters/update-message"
const returned = {
  entity_kind: "outlook_message",
  mailbox_id: "returned-scope",
  message_id: "returned-id",
  label: "Returned copy",
}
const source = {
  ...returned,
  mailbox_id: "approved-scope",
  message_id: "source-id",
  label: "Approved source",
}
function render(node: ReactNode, conversationId: string | null = "conversation") {
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: new QueryClient() },
      createElement(ToolConversationContext, { value: conversationId }, node)
    )
  )
}
function outcome(
  presenter: ToolRowPresenter,
  name: string,
  args: unknown,
  status: ToolActivity["status"],
  result?: unknown
) {
  return presenter.render({
    activity: { id: "call", kind: "result", name, status, args, result },
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "outlook_mail",
  })
}
function results(state: string, webLink: unknown = null) {
  return {
    results: [
      {
        provider_key: "outlook_mail",
        display_name: "Mailbox",
        external_id: "returned-scope",
        status: state === "unverified" ? "error" : "success",
        error_code: state === "unverified" ? "unverified_mutation" : null,
        error_message: null,
        data: {
          message: returned,
          outcome: state,
          web_link: webLink,
          detail: null,
          error_code: null,
        },
      },
    ],
  }
}
const cases: [ToolRowPresenter, string, Record<string, unknown>][] = [
  [
    outlookMailReplyPresenter,
    "outlook_mail_reply_to_message",
    { message: source, body_html: "", reply_all: false },
  ],
  [
    outlookMailForwardPresenter,
    "outlook_mail_forward_message",
    { message: source, to: ["a@example.com"], body_html: "" },
  ],
  [
    outlookMailDraftPresenter,
    "outlook_mail_create_draft",
    { reply_to: source, body_html: "", reply_all: false },
  ],
  [
    outlookMailMovePresenter,
    "outlook_mail_move_message",
    { message: source, destination_folder: "archive" },
  ],
  [outlookMailUpdatePresenter, "outlook_mail_update_message", { message: source, is_read: true }],
]
describe("Outlook returned and approved message references", () => {
  it.each(["applied", "failed", "unverified"])(
    "retains %s recovery with missing and unsafe links",
    (state) => {
      for (const webLink of [null, "javascript:alert(1)"]) {
        expect(
          outlookWriteResult({ message: returned, outcome: state, web_link: webLink })?.message
        ).toEqual({ label: "Returned copy", mailboxId: "returned-scope", messageId: "returned-id" })
        const node = outcome(
          outlookMailSendPresenter,
          "outlook_mail_send_message",
          { to: ["a@example.com"], subject: "New email", body_html: "" },
          "completed",
          results(state, webLink)
        )
        const html = render(node)
        expect(html).toContain("Returned message: ")
        expect(html).toContain("Returned copy")
        expect(html).toContain("View returned message")
        expect(html).not.toContain("javascript:")
        expect(html).not.toContain("returned-id")
        expect(html).not.toContain("returned-scope")
        expect(render(node, null)).toContain("Message unavailable")
      }
    }
  )
  it.each(cases)("identifies sources across settled states: %s %s", (presenter, name, args) => {
    for (const status of ["completed", "denied", "failed"] as const) {
      for (const label of ["First approved email", "Second approved email"]) {
        const field = name === "outlook_mail_create_draft" ? "reply_to" : "message"
        const html = render(
          outcome(
            presenter,
            name,
            { ...args, [field]: { ...source, label } },
            status,
            status === "completed" ? results("applied") : undefined
          )
        )
        expect(html).toContain("Source message")
        expect(html).toContain(label)
        expect(html).not.toContain("approved-scope")
        expect(html).not.toContain("source-id")
        if (status === "completed") {
          expect(html).toContain("Returned message:")
          expect(html).toContain("Returned copy")
        }
      }
    }
  })
})
