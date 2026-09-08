// apps/web/tests/integrations/outlook_mail/write-presenters.test.ts

import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeAll, describe, expect, it, vi } from "vitest"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-card"
import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import type { ToolActivity } from "@/features/conversations/message-parts"
import type { ToolUiField } from "@/features/tools/types"
import type { ToolRowPresenter, ToolRowPresenterProps } from "@/integrations/contract"
import { outlookMailDraftPresenter } from "@/integrations/outlook_mail/presenters/create-draft"
import { outlookMailForwardPresenter } from "@/integrations/outlook_mail/presenters/forward-message"
import { outlookMailMovePresenter } from "@/integrations/outlook_mail/presenters/move-message"
import { outlookMailReplyPresenter } from "@/integrations/outlook_mail/presenters/reply-to-message"
import { outlookMailSendDraftPresenter } from "@/integrations/outlook_mail/presenters/send-draft"
import { outlookMailSendPresenter } from "@/integrations/outlook_mail/presenters/send-message"
import { outlookMailUpdatePresenter } from "@/integrations/outlook_mail/presenters/update-message"
import { loadIntegrationUiModules } from "@/integrations/registry"

const message = {
  version: 1,
  entity_kind: "outlook_message",
  mailbox_id: "opaque-mailbox",
  message_id: "message",
  label: "Outlook message",
}

const ARGS: Record<string, unknown> = {
  outlook_mail_send_draft: {
    message,
    _draft: {
      fingerprint: "a".repeat(64),
      subject: "Reviewed draft",
      body: "<p>Draft content</p>",
      body_type: "html",
      from: "dana@example.com",
      sender: "dana@example.com",
      to: ["kai@example.com"],
      cc: [],
      bcc: [],
      reply_to: [],
    },
  },
  outlook_mail_send_message: {
    to: ["kai@example.com"],
    subject: "Monthly report",
    body_html: "<p>Report attached</p>",
    cc: ["dana@example.com"],
    bcc: null,
  },
  outlook_mail_reply_to_message: { message, body_html: "<p>Thanks</p>", reply_all: true },
  outlook_mail_forward_message: { message, to: ["kai@example.com"], body_html: "" },
  outlook_mail_create_draft: {
    to: ["kai@example.com"],
    subject: "Draft report",
    body_html: "<p>Draft</p>",
    cc: null,
    bcc: null,
    reply_to: null,
    reply_all: false,
  },
  outlook_mail_move_message: { message, destination_folder: "archive" },
  outlook_mail_update_message: { message, is_read: true, flagged: false },
}

const PRESENTERS: Record<string, ToolRowPresenter> = {
  outlook_mail_send_draft: outlookMailSendDraftPresenter,
  outlook_mail_send_message: outlookMailSendPresenter,
  outlook_mail_reply_to_message: outlookMailReplyPresenter,
  outlook_mail_forward_message: outlookMailForwardPresenter,
  outlook_mail_create_draft: outlookMailDraftPresenter,
  outlook_mail_move_message: outlookMailMovePresenter,
  outlook_mail_update_message: outlookMailUpdatePresenter,
}

const NAMES = Object.keys(PRESENTERS)

// Mirrors the server's declared approval fields so entity references use the entity editor.
const FIELDS: Record<string, [string, ToolUiField["format"]][]> = {
  outlook_mail_send_message: [
    ["to", "list"],
    ["subject", "text"],
    ["body_html", "html"],
    ["cc", "list"],
    ["bcc", "list"],
  ],
  outlook_mail_reply_to_message: [
    ["message", "entity"],
    ["body_html", "html"],
    ["reply_all", "boolean"],
  ],
  outlook_mail_forward_message: [
    ["message", "entity"],
    ["to", "list"],
    ["body_html", "html"],
  ],
  outlook_mail_create_draft: [
    ["to", "list"],
    ["subject", "text"],
    ["body_html", "html"],
    ["cc", "list"],
    ["bcc", "list"],
    ["reply_to", "entity"],
    ["reply_all", "boolean"],
  ],
  outlook_mail_move_message: [
    ["message", "entity"],
    ["destination_folder", "text"],
  ],
  outlook_mail_update_message: [
    ["message", "entity"],
    ["is_read", "boolean"],
    ["flagged", "boolean"],
  ],
}

function render(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } })
  return renderToStaticMarkup(
    createElement(QueryClientProvider, { client }, createElement("div", null, node))
  )
}

function props(
  name: string,
  status: ToolActivity["status"],
  overrides: Partial<ToolActivity> = {}
): ToolRowPresenterProps {
  return {
    activity: { id: "call", kind: "call", name, status, args: ARGS[name], ...overrides },
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "outlook_mail",
  }
}

function controls(): ToolApprovalDecisionControls {
  return {
    decision: { decision: "pending", edits: {}, message: "" },
    disabled: false,
    error: null,
    onDecisionChange: vi.fn(),
    onRetry: vi.fn(),
    pendingCount: 1,
    submitting: false,
  }
}

function entry(data: unknown, overrides: Record<string, unknown> = {}) {
  return {
    provider_key: "outlook_mail",
    display_name: "Operations mailbox",
    external_id: "opaque-mailbox",
    status: "success",
    data,
    error_code: null,
    error_message: null,
    ...overrides,
  }
}

function applied(overrides: Record<string, unknown> = {}) {
  return {
    message,
    outcome: "applied",
    web_link: {
      node: "praxis_untrusted",
      source_kind: "outlook_message",
      source_ref: "message",
      content: "https://outlook.office.com/mail/id/message",
    },
    error_code: null,
    detail: null,
    ...overrides,
  }
}

function completed(name: string, results: unknown[]) {
  return render(
    PRESENTERS[name]?.render(props(name, "completed", { kind: "result", result: { results } }))
  )
}

describe("Outlook write presenters", () => {
  beforeAll(async () => {
    await loadIntegrationUiModules(["outlook_mail"])
  })

  it.each(NAMES)("registers %s with its own approval-aware presenter", (name) => {
    const presenter = PRESENTERS[name]
    expect(presenter?.handlesApprovals).toBe(true)
    expect(presenter?.matches(props(name, "completed").activity)).toBe(true)
    expect(NAMES.filter((other) => presenter?.matches(props(other, "completed").activity))).toEqual(
      [name]
    )
    const context = props(name, "awaiting_approval")
    context.approvalDecision = controls()
    expect(renderCustomToolCallRow(context)).not.toBeNull()
  })

  it.each([
    ["outlook_mail_send_message", "Review email before sending", "Approve &amp; Send"],
    ["outlook_mail_send_draft", "Review draft before sending", "Approve &amp; Send"],
    ["outlook_mail_reply_to_message", "Review reply before sending", "Approve &amp; Send"],
    ["outlook_mail_forward_message", "Review email before forwarding", "Approve &amp; Forward"],
    ["outlook_mail_create_draft", "Review draft before saving", "Approve &amp; Save"],
    ["outlook_mail_move_message", "Review message move", "Approve &amp; Move"],
    ["outlook_mail_update_message", "Review message update", "Approve &amp; Update"],
  ])("renders a branded approval card for %s", (name, title, approve) => {
    const context = props(name, "awaiting_approval")
    context.approvalDecision = controls()
    context.ui = {
      icon: "outlook_mail",
      running_label: "",
      completed_label: "",
      failed_label: "",
      approval_title: "",
      approval_prompt: "",
      approve_label: "",
      arg_fields: (FIELDS[name] ?? []).map(([key, format]) => ({
        key,
        label: key,
        format,
        editable: true,
        min_rows: 0,
        options: [],
        placeholder: "",
        secondary: false,
        ...(format === "entity" ? { entity_kind: "outlook_message" } : {}),
      })),
      result_fields: [],
    }
    const html = render(PRESENTERS[name]?.render(context))
    expect(html).toContain(`Approval request: ${title}`)
    expect(html).toContain(approve)
    expect(html).toContain("<svg")
    expect(html).not.toContain("opaque-mailbox")
  })

  it.each([
    [
      "outlook_mail_create_draft",
      { ...(ARGS["outlook_mail_create_draft"] as object), reply_to: message },
      "A reply draft cannot set To or Subject.",
    ],
    [
      "outlook_mail_create_draft",
      { to: ["kai@example.com"], subject: "Draft", body_html: "", reply_all: true },
      "Reply all needs a message to reply to.",
    ],
    ["outlook_mail_create_draft", { body_html: "" }, "A new draft needs To and Subject."],
    [
      "outlook_mail_update_message",
      { message, is_read: null, flagged: null },
      "Set Read or Flagged to update a message.",
    ],
  ])("blocks approval of an invalid %s with a plain reason", (name, args, reason) => {
    const context = props(name, "awaiting_approval", { args })
    context.approvalDecision = controls()
    expect(render(PRESENTERS[name]?.render(context))).toContain(reason)
  })

  it.each([
    ["running", "Sending email…"],
    ["awaiting_approval", "Waiting for approval to send this email…"],
    ["failed", "The email could not be sent."],
  ] as const)("renders the %s state for a send", (status, copy) => {
    const html = render(outlookMailSendPresenter.render(props("outlook_mail_send_message", status)))
    expect(html).toContain("Send Outlook Email")
    expect(html).toContain(copy)
    if (status === "failed") {
      expect(html).toContain("Email not sent")
      expect(html).toContain("Monthly report")
      expect(html).not.toContain("Open in Outlook")
    }
  })

  it("keeps a declined send distinct from a failure and shows the reason", () => {
    const html = render(
      outlookMailSendPresenter.render(
        props("outlook_mail_send_message", "denied", { decisionReason: "Wrong recipient" })
      )
    )
    expect(html).toContain("This email was declined and was not sent.")
    expect(html).toContain("Wrong recipient")
    expect(html).toContain("Subject: Monthly report")
    expect(html).not.toContain(">Failed<")
  })

  it.each([
    [
      "outlook_mail_send_message",
      [
        "Email sent",
        "Outlook accepted the email for sending.",
        "Monthly report",
        "kai@example.com",
        "dana@example.com",
        "Report attached",
      ],
    ],
    ["outlook_mail_reply_to_message", ["Reply sent", "Reply all", "Yes", "Thanks"]],
    ["outlook_mail_send_draft", ["Draft sent", "Outlook accepted the existing draft for sending."]],
    ["outlook_mail_forward_message", ["Email forwarded", "kai@example.com"]],
    [
      "outlook_mail_create_draft",
      ["Draft saved", "Nothing was sent.", "Draft report", "Open draft in Outlook"],
    ],
    ["outlook_mail_move_message", ["Message moved", "Folder", "Archive"]],
    ["outlook_mail_update_message", ["Message updated", "Read", "Not flagged"]],
  ])("renders the confirmed outcome for %s from the approved arguments", (name, expected) => {
    const html = completed(name, [entry(applied())])
    for (const text of expected) expect(html).toContain(text)
    expect(html).toContain("https://outlook.office.com/mail/id/message")
    expect(html).toContain(">Done<")
    expect(html).toContain("Operations mailbox")
    expect(html).not.toContain("opaque-mailbox")
    expect(html).not.toContain("praxis_untrusted")
  })

  const outcomes = [
    ["outlook_mail_send_message", "Send not confirmed", "Email not sent"],
    ["outlook_mail_send_draft", "Send not confirmed", "Draft not sent"],
    ["outlook_mail_reply_to_message", "Reply not confirmed", "Reply not sent"],
    ["outlook_mail_forward_message", "Forward not confirmed", "Email not forwarded"],
    ["outlook_mail_create_draft", "Draft not confirmed", "Draft not saved"],
    ["outlook_mail_move_message", "Move not confirmed", "Message not moved"],
    ["outlook_mail_update_message", "Update not confirmed", "Message not updated"],
  ]

  it.each(outcomes)("preserves uncertain evidence throughout %s", (name, title, rejected) => {
    const ambiguous = (data: unknown) =>
      completed(name, [
        entry(data, {
          status: "error",
          error_code: "unverified_mutation",
        }),
      ])
    const states = [
      render(PRESENTERS[name]?.render(props(name, "unknown"))),
      render(PRESENTERS[name]?.render(props(name, "completed"))),
      completed(name, [entry({ outcome: "applied" })]),
      ambiguous(applied({ outcome: "unverified" })),
      ambiguous(null),
      ambiguous({ outcome: "unverified", message: "invalid" }),
      completed(name, [entry(applied({ outcome: "unverified" }))]),
    ]
    for (const html of states) {
      expect(html).toContain(`aria-label="${title}"`)
      expect(html).toContain(">Unconfirmed<")
      expect(html).not.toContain(">Failed<")
      expect(html).not.toContain(">Done<")
      expect(html).not.toContain(rejected)
      expect(html).not.toContain("Open draft in Outlook")
    }
    expect(states[3]).toContain("Open in Outlook")
  })

  it.each(outcomes)(
    "keeps confirmed rejection and denial distinct for %s",
    (name, title, rejected) => {
      const failed = completed(name, [entry(applied({ outcome: "failed" }))])
      expect(failed).toContain(`aria-label="${rejected}"`)
      expect(failed).toContain(">Failed<")
      expect(failed).not.toContain(title)
      const denied = render(PRESENTERS[name]?.render(props(name, "denied")))
      expect(denied).toContain(">Declined<")
      expect(denied).not.toContain(">Failed<")
      expect(denied).not.toContain(">Unconfirmed<")
    }
  )

  it("does not render an empty forward body frame", () => {
    expect(completed("outlook_mail_forward_message", [entry(applied())])).not.toContain("<iframe")
    expect(completed("outlook_mail_send_message", [entry(applied())])).toContain("<iframe")
  })

  it("shows a rejected send as failed with the draft that remains", () => {
    const html = completed("outlook_mail_send_message", [
      entry(
        applied({
          outcome: "failed",
          error_code: "send_failed",
          detail: "The draft remains in Drafts. Nothing was sent.",
        })
      ),
    ])
    expect(html).toContain("Email not sent")
    expect(html).toContain("The draft remains in Drafts. Nothing was sent.")
    expect(html).toContain("Open draft in Outlook")
    expect(html).toContain(">Failed<")
    expect(html).not.toContain(">Done<")
    expect(html).not.toContain("Email sent")
  })

  it("shows an unverified send as unconfirmed rather than sent or failed", () => {
    const html = completed("outlook_mail_send_message", [
      entry(applied({ outcome: "unverified", error_code: "unverified_mutation" }), {
        status: "error",
        error_code: "unverified_mutation",
        error_message: "Raw provider message",
      }),
    ])
    expect(html).toContain("Send not confirmed")
    expect(html).toContain("couldn&#x27;t verify whether Outlook sent this email")
    expect(html).toContain("Open in Outlook")
    expect(html).not.toContain("Open draft in Outlook")
    expect(html).not.toContain("Raw provider message")
    expect(html).not.toContain("Email sent")
  })

  it("shows a provider error without result data as a failed change", () => {
    const html = completed("outlook_mail_move_message", [
      entry(null, {
        status: "error",
        error_code: "folder_not_found",
        error_message: "No folder is named Archive.",
      }),
    ])
    expect(html).toContain("Message not moved")
    expect(html).toContain("No folder is named Archive.")
    expect(html).not.toContain("Open in Outlook")
  })

  it("fails closed on malformed or missing confirmation", () => {
    const missingMessage = completed("outlook_mail_update_message", [
      entry(applied({ message: null })),
    ])
    expect(missingMessage).toContain("could not confirm that this message was updated")
    expect(missingMessage).not.toContain("Message updated")
    const html = render(
      outlookMailUpdatePresenter.render(props("outlook_mail_update_message", "completed"))
    )
    expect(html).toContain("could not confirm that this message was updated")
  })
})
