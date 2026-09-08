// apps/web/tests/integrations/outlook_mail/write-approvals.test.ts

import { createElement, type MouseEvent, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"

import { ApprovalRequestFields, type ApprovalField } from "@/components/tool-ui/approval-card"
import { OutlookReplyRecipients } from "@/integrations/outlook_mail/components/reply-recipients"
import { outlookDraftArgs } from "@/integrations/outlook_mail/lib/write-args"
import { Button } from "@/components/ui/button"
import { Select } from "@/components/ui/select"
import { Checkbox } from "@/components/ui/checkbox"
import { buildResumeDecisions } from "@/features/conversations/approval-decisions"
import type { EditedValues } from "@/components/tool-ui/edited-values"

vi.mock("@/components/ui/checkbox", async (importOriginal) => {
  const original = await importOriginal<{ Checkbox: typeof Checkbox }>()
  return { ...original, Checkbox: vi.fn(original.Checkbox) }
})

vi.mock("@/components/ui/button", async (importOriginal) => {
  const original = await importOriginal<{ Button: typeof Button }>()
  return { ...original, Button: vi.fn(original.Button) }
})

vi.mock("@/components/ui/select", async (importOriginal) => {
  const original = await importOriginal<{ Select: typeof Select }>()
  return { ...original, Select: vi.fn(original.Select) }
})

function field(key: string, format: ApprovalField["format"], secondary = false): ApprovalField {
  return {
    key,
    label: key,
    format,
    secondary,
    editable: true,
    min_rows: 0,
    options: [],
    placeholder: "",
  }
}

function render(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
  return renderToStaticMarkup(createElement(QueryClientProvider, { client }, node))
}

const message = {
  version: 1,
  entity_kind: "outlook_message",
  mailbox_id: "mailbox",
  message_id: "message",
  label: "Original email",
}

describe("Outlook approval fidelity", () => {
  it("retains a null secondary reply target while editing a new draft", () => {
    const args = {
      to: ["dana@example.com"],
      subject: "Review",
      body_html: "<p>Review</p>",
      reply_to: null,
      reply_all: false,
      cc: null,
      bcc: null,
    }
    const fields = [
      field("to", "list", true),
      field("subject", "text", true),
      field("body_html", "html"),
      field("reply_to", "entity", true),
      field("reply_all", "boolean"),
    ]
    const html = render(
      createElement(ApprovalRequestFields, {
        activityId: "draft",
        args,
        fields,
        fallbackFields: [],
        disabled: false,
        decision: { decision: "pending", edits: {}, message: "" },
        onEditsChange: vi.fn(),
      })
    )
    expect(html).not.toContain("Target unavailable")
    expect(html).toContain("Review")
    const decisions = buildResumeDecisions(
      [{ tool_call_id: "draft", name: "outlook_mail_create_draft", args }],
      {
        draft: { decision: "approved", edits: { subject: "Updated review" }, message: "" },
      },
      () => fields
    )
    expect(decisions).toEqual([
      {
        tool_call_id: "draft",
        decision: "approved",
        override_args: { ...args, subject: "Updated review", reply_to: null },
      },
    ])
  })

  it("edits Reply all as a checkbox and submits a JSON boolean", () => {
    vi.mocked(Checkbox).mockClear()
    const fields = [field("reply_all", "boolean")]
    const args = { message, body_html: "<p>Reply</p>", reply_all: false }
    const onEditsChange = vi.fn<(edits: EditedValues) => void>()
    const html = render(
      createElement(ApprovalRequestFields, {
        activityId: "reply",
        args,
        fields,
        fallbackFields: [],
        disabled: false,
        decision: { decision: "pending", edits: {}, message: "" },
        onEditsChange,
      })
    )
    expect(html).toContain('role="checkbox"')
    expect(html).toContain('aria-checked="false"')
    vi.mocked(Checkbox).mock.calls[0]?.[0].onCheckedChange?.(true, {
      reason: "none",
      event: new Event("change"),
      cancel: () => undefined,
      allowPropagation: () => undefined,
      isCanceled: false,
      isPropagationAllowed: false,
      trigger: undefined,
    })
    const edits = onEditsChange.mock.calls[0]?.[0] ?? {}
    expect(edits).toEqual({ reply_all: true })
    expect(
      buildResumeDecisions(
        [{ tool_call_id: "reply", name: "outlook_mail_reply_to_message", args }],
        {
          reply: { decision: "approved", edits, message: "" },
        },
        () => fields
      )
    ).toEqual([
      { tool_call_id: "reply", decision: "approved", override_args: { ...args, reply_all: true } },
    ])
  })

  it.each(["", "  <p>Edited reply</p>\n"])("preserves the exact approved HTML %j", (body_html) => {
    const args = { message, to: ["kai@example.com"], body_html: "<p>Original</p>" }
    expect(
      buildResumeDecisions(
        [{ tool_call_id: "forward", name: "outlook_mail_forward_message", args }],
        {
          forward: { decision: "approved", edits: { body_html }, message: "" },
        },
        () => [field("body_html", "html")]
      )
    ).toEqual([
      { tool_call_id: "forward", decision: "approved", override_args: { ...args, body_html } },
    ])
  })
})

describe("Reply draft recipient inheritance", () => {
  it.each([undefined, null, [], ["lee@example.com"]])(
    "preserves recipient intent %j while editing the body",
    (recipients) => {
      const replay = {
        reply_to: message,
        body_html: "<p>Proposed</p>",
        ...(recipients === undefined ? {} : { cc: recipients, bcc: recipients }),
      }
      const display = {
        ...replay,
        cc: recipients ?? null,
        bcc: recipients ?? null,
        _recipient_inheritance: ["to"],
      }
      const fields = [
        field("body_html", "html"),
        field("cc", "list", true),
        field("bcc", "list", true),
      ]
      const result = buildResumeDecisions(
        [
          {
            tool_call_id: "draft",
            name: "outlook_mail_create_draft",
            args: display,
            replay_args: replay,
          },
        ],
        { draft: { decision: "approved", edits: { body_html: "<p>Edited</p>" }, message: "" } },
        () => fields
      )
      expect(result).toEqual([
        {
          tool_call_id: "draft",
          decision: "approved",
          override_args: { ...replay, body_html: "<p>Edited</p>" },
        },
      ])
      const html = render(
        createElement(OutlookReplyRecipients, {
          args: outlookDraftArgs(display),
          disabled: false,
          onFieldEdit: vi.fn(),
        })
      )
      expect(html).toContain(
        recipients == null
          ? "Keep reply recipients from Outlook"
          : recipients.length
            ? "lee@example.com"
            : "No recipients"
      )
    }
  )

  it("clears inherited Cc with an explicit empty list", () => {
    vi.mocked(Button).mockClear()
    const args = { reply_to: message, body_html: "<p>Reply</p>", cc: null, bcc: null }
    const onFieldEdit = vi.fn()
    render(
      createElement(OutlookReplyRecipients, {
        args: outlookDraftArgs(args),
        disabled: false,
        onFieldEdit,
      })
    )
    const clear = vi
      .mocked(Button)
      .mock.calls.find(([props]) => Array.isArray(props.children) && props.children.includes("Cc"))
    expect(clear).toBeDefined()
    clear?.[0].onClick?.({
      ...({ type: "click" } as MouseEvent<HTMLButtonElement>),
      preventBaseUIHandler: vi.fn(),
    })
    expect(onFieldEdit).toHaveBeenCalledWith("cc", [])
    expect(
      buildResumeDecisions(
        [{ tool_call_id: "draft", name: "outlook_mail_create_draft", args }],
        { draft: { decision: "approved", edits: { cc: [] }, message: "" } },
        () => [field("cc", "list", true)]
      )
    ).toEqual([{ tool_call_id: "draft", decision: "approved", override_args: { ...args, cc: [] } }])
  })

  it("replaces inherited recipients only for declared optional lists", () => {
    const args = { cc: null }
    const decisions = {
      draft: {
        decision: "approved" as const,
        edits: { cc: ["lee@example.com"] },
        message: "" as const,
      },
    }
    const approvals = [{ tool_call_id: "draft", name: "outlook_mail_create_draft", args }]
    expect(buildResumeDecisions(approvals, decisions, () => [field("cc", "list", true)])).toEqual([
      { tool_call_id: "draft", decision: "approved", override_args: { cc: ["lee@example.com"] } },
    ])
    expect(typeof buildResumeDecisions(approvals, decisions, () => [field("cc", "list")])).toBe(
      "string"
    )
    expect(typeof buildResumeDecisions(approvals, decisions)).toBe("string")
  })
})

describe("Optional update flags", () => {
  const fields = [
    field("is_read", "boolean", true),
    field("flagged", "boolean", true),
    field("subject", "text"),
  ]
  function show(args: Record<string, unknown>, edits: EditedValues = {}) {
    vi.mocked(Select).mockClear()
    vi.mocked(Checkbox).mockClear()
    const onEditsChange = vi.fn<(edits: EditedValues) => void>()
    const html = render(
      createElement(ApprovalRequestFields, {
        activityId: "update",
        args,
        fields,
        fallbackFields: [],
        disabled: false,
        decision: { decision: "pending", edits, message: "" },
        onEditsChange,
      })
    )
    return { html, onEditsChange }
  }
  function resume(args: Record<string, unknown>, edits: EditedValues) {
    return buildResumeDecisions(
      [{ tool_call_id: "update", name: "outlook_mail_update_message", args }],
      {
        update: { decision: "approved", edits, message: "" },
      },
      () => fields
    )
  }
  function select(value: string) {
    vi.mocked(Select).mock.calls[0]?.[0].onValueChange?.(value, {
      reason: "none",
      event: new Event("change"),
      cancel: () => undefined,
      allowPropagation: () => undefined,
      isCanceled: false,
      isPropagationAllowed: false,
      trigger: undefined,
    })
  }

  it.each([undefined, null])(
    "deliberately adds either boolean from %j and can remove the addition",
    (initial) => {
      const args = {
        message,
        is_read: true,
        subject: "Original",
        ...(initial === undefined ? {} : { flagged: initial }),
      }
      const first = show(args)
      expect(first.html).toContain("No change")
      expect(first.onEditsChange).not.toHaveBeenCalled()
      expect(resume(args, {})).toEqual([
        { tool_call_id: "update", decision: "approved", override_args: null },
      ])
      for (const value of [true, false]) {
        const control = show(args)
        expect(vi.mocked(Select).mock.calls).toHaveLength(1)
        select(String(value))
        const edits = control.onEditsChange.mock.calls[0]?.[0] ?? {}
        expect(edits).toEqual({ flagged: value })
        expect(resume(args, edits)).toEqual([
          {
            tool_call_id: "update",
            decision: "approved",
            override_args: { ...args, flagged: value },
          },
        ])
        const edited = show(args, { ...edits, subject: "Changed" })
        select("unchanged")
        const remaining = edited.onEditsChange.mock.calls[0]?.[0] ?? {}
        expect(remaining).toEqual({ subject: "Changed" })
        expect(resume(args, remaining)).toEqual([
          {
            tool_call_id: "update",
            decision: "approved",
            override_args: { ...args, subject: "Changed" },
          },
        ])
      }
    }
  )

  it.each([true, false])("preserves the existing checkbox and resume type for %j", (initial) => {
    const args = { message, is_read: initial, flagged: initial }
    show(args)
    expect(vi.mocked(Select).mock.calls).toHaveLength(0)
    const props = vi.mocked(Checkbox).mock.calls[0]?.[0]
    expect(props?.checked).toBe(initial)
    expect(resume(args, { is_read: initial })).toEqual([
      { tool_call_id: "update", decision: "approved", override_args: null },
    ])
  })

  it("preserves two absent flags during unrelated edits", () => {
    const args = { message, subject: "Original" }
    const { onEditsChange } = show(args)
    expect(vi.mocked(Select).mock.calls).toHaveLength(2)
    expect(onEditsChange).not.toHaveBeenCalled()
    expect(resume(args, { subject: "Changed" })).toEqual([
      {
        tool_call_id: "update",
        decision: "approved",
        override_args: { ...args, subject: "Changed" },
      },
    ])
  })

  it.each(["false", 0, {}, []])(
    "rejects malformed original boolean %j in the editor and resume",
    (flagged) => {
      const args = { message, is_read: true, flagged }
      show(args)
      expect(vi.mocked(Select).mock.calls).toHaveLength(0)
      expect(typeof resume(args, { flagged: false })).toBe("string")
    }
  )

  it("does not expose an absent primary boolean editor", () => {
    vi.mocked(Select).mockClear()
    const html = render(
      createElement(ApprovalRequestFields, {
        activityId: "primary",
        args: { flagged: null },
        fields: [field("flagged", "boolean")],
        fallbackFields: [],
        disabled: false,
        decision: { decision: "pending", edits: {}, message: "" },
        onEditsChange: vi.fn(),
      })
    )
    expect(html).not.toContain("No change")
    expect(vi.mocked(Select).mock.calls).toHaveLength(0)
  })

  it("rejects additions to undeclared, primary, or read-only boolean fields", () => {
    for (const declared of [
      undefined,
      [field("flagged", "boolean")],
      [{ ...field("flagged", "boolean", true), editable: false }],
    ]) {
      expect(
        typeof buildResumeDecisions(
          [
            {
              tool_call_id: "update",
              name: "outlook_mail_update_message",
              args: { flagged: null },
            },
          ],
          {
            update: { decision: "approved", edits: { flagged: false }, message: "" },
          },
          () => declared
        )
      ).toBe("string")
    }
  })
})

describe("Recipient accessible names", () => {
  it("distinguishes To, Cc and Bcc inputs and removals even for the same address", () => {
    const labels = ["To", "Cc", "Bcc"]
    const html = render(
      createElement(ApprovalRequestFields, {
        activityId: "recipients",
        args: { to: ["same@example.com"], cc: ["same@example.com"], bcc: ["same@example.com"] },
        fields: labels.map((label) => ({ ...field(label.toLowerCase(), "list", true), label })),
        fallbackFields: [],
        disabled: false,
        decision: { decision: "pending", edits: {}, message: "" },
        onEditsChange: vi.fn(),
      })
    )
    for (const label of labels) {
      expect(html).toContain(`aria-label="Add item to ${label}"`)
      expect(html).toContain(`aria-label="Remove same@example.com from ${label}"`)
    }
  })
})
