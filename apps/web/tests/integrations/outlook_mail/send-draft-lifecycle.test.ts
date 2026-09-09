import { createElement, type MouseEvent } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeAll, describe, expect, it, vi } from "vitest"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-card"
import { Button } from "@/components/ui/button"
import { buildResumeDecisions } from "@/features/conversations/approval-decisions"
import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import { useInlineApprovals } from "@/features/conversations/hooks/use-inline-approvals"
import { projectConversationTimeline } from "@/features/conversations/message-parts/timeline"
import type { ToolActivity } from "@/features/conversations/message-parts"
import type { PendingToolApproval } from "@/features/conversations/types"
import { loadIntegrationUiModules } from "@/integrations/registry"

vi.mock("@/components/ui/button", async (importOriginal) => {
  const original = await importOriginal<{ Button: typeof Button }>()
  return { ...original, Button: vi.fn(original.Button) }
})

const message = {
  version: 1,
  entity_kind: "outlook_message",
  mailbox_id: "reviewed-mailbox",
  message_id: "saved-draft",
  label: "Saved reply",
}
const snapshot = {
  fingerprint: "a".repeat(64),
  subject: "Reviewed subject",
  body: "Reviewed text body",
  body_type: "text",
  from: "dana@example.com",
  sender: "amal@example.com",
  to: ["kai@example.com"],
  cc: ["lee@example.com"],
  bcc: ["quinn@example.com"],
  reply_to: ["alex@example.com"],
}

function pending(nested: boolean, draft: unknown = snapshot): PendingToolApproval {
  return {
    tool_call_id: nested ? "workflow:1" : "send-draft",
    name: "outlook_mail_send_draft",
    args: { message, ...(draft === null ? {} : { _draft: draft }) },
    replay_args: { message },
  }
}

function project(approval: PendingToolApproval, nested: boolean) {
  const timeline = projectConversationTimeline({
    approvals: [approval],
    assistantAgentId: "agent",
    conversationId: "conversation",
    pendingDelegations: [],
    pendingUserMessages: [],
    transcriptRun: { id: "active-run", status: "awaiting_approval" },
    stream: {
      approvals: [],
      conversationId: "conversation",
      isStreaming: false,
      messages: [],
      runId: null,
      toolCalls: [],
    },
    pendingWorkflow: nested
      ? {
          outer_tool_call_id: "workflow",
          code: "await outlook_mail_send_draft(message=message)",
          reason: null,
          status: "suspended",
          nested_trace: [],
          trace_truncated: false,
          pending: { ...approval, parent_tool_call_id: "workflow" },
          recovery: null,
        }
      : null,
    messages: [
      {
        id: "assistant-call",
        conversation_id: "conversation",
        client_message_id: null,
        created_at: "2026-09-08T10:00:00Z",
        updated_at: "2026-09-08T10:00:00Z",
        error: null,
        metadata: { agent_run_id: "active-run" },
        role: "assistant",
        sequence: 1,
        tool_name: null,
        parts: {
          parts: [
            {
              part_kind: "tool-call",
              tool_call_id: nested ? "workflow" : approval.tool_call_id,
              tool_name: nested ? "run_workflow" : approval.name,
              args: nested
                ? { code: "await outlook_mail_send_draft(message=message)" }
                : { message },
            },
          ],
        },
      },
    ],
  })
  const activities = timeline.rows.flatMap((row) => {
    if (row.kind === "pending-message") return []
    if (row.kind === "assistant-turn") return row.messages.flatMap((item) => item.toolActivities)
    return row.message.toolActivities
  })
  const activity = nested ? activities[0]?.script?.children[0] : activities[0]
  expect(timeline.orphanApprovals).toEqual([])
  expect(activity).toMatchObject({
    id: approval.tool_call_id,
    agentRunId: "active-run",
    status: "awaiting_approval",
    args: approval.args,
  })
  if (!activity) throw new Error("Missing projected draft approval")
  return activity
}

function render(activity: ToolActivity, controls: ToolApprovalDecisionControls) {
  vi.mocked(Button).mockClear()
  const row = renderCustomToolCallRow({
    activity,
    approvalDecision: controls,
    providerKey: "outlook_mail",
    compact: false,
    defaultOpen: true,
    live: false,
  })
  expect(row).not.toBeNull()
  return renderToStaticMarkup(row)
}

function controls(
  overrides: Partial<ToolApprovalDecisionControls> = {}
): ToolApprovalDecisionControls {
  return {
    decision: { decision: "pending", edits: {}, message: "" },
    error: null,
    pendingCount: 1,
    submitting: false,
    onDecisionChange: vi.fn(),
    onRetry: vi.fn(),
    ...overrides,
  }
}

function click(label: string) {
  const button = vi.mocked(Button).mock.calls.find(([props]) => props.children === label)?.[0]
  expect(button).toBeDefined()
  expect(button?.disabled).not.toBe(true)
  button?.onClick?.({
    ...({ type: "click" } as MouseEvent<HTMLButtonElement>),
    preventBaseUIHandler: vi.fn(),
  })
}

function assertReview(html: string) {
  for (const value of [
    "Review draft before sending",
    "dana@example.com (sent by amal@example.com)",
    "kai@example.com",
    "lee@example.com",
    "quinn@example.com",
    "alex@example.com",
    "Reviewed subject",
  ])
    expect(html).toContain(value)
  expect(html).not.toContain(snapshot.fingerprint)
  expect(html).not.toContain("<input")
  expect(html).not.toContain("<textarea")
}

beforeAll(async () => {
  await loadIntegrationUiModules(["outlook_mail"])
})

const approvalCases = [
  [false, null],
  [true, null],
  [false, "c".repeat(64)],
  [true, "c".repeat(64)],
] as const

describe.each(approvalCases)("saved-draft approval (%s, %s)", (nested, revision) => {
  it.each(["text", "html"])(
    "projects the complete read-only %s review and submits only its call identity",
    async (bodyType) => {
      const draft = {
        ...snapshot,
        body_type: bodyType,
        body: bodyType === "html" ? "<p>Reviewed HTML body</p>" : snapshot.body,
      }
      const approval = pending(nested, draft)
      const activity = project(approval, nested)
      const submit = vi.fn().mockResolvedValue(undefined)
      function ApprovalProbe() {
        const { resolveApprovalControls } = useInlineApprovals({
          activeRunId: "active-run",
          approvalRevision: revision,
          approvals: [approval],
          enabled: true,
          isSubmitting: false,
          onSubmit: submit,
        })
        expect(
          resolveApprovalControls({ ...activity, agentRunId: "old-run", rootRunId: "old-run" })
        ).toBeNull()
        const bound = resolveApprovalControls(activity)
        if (!bound) throw new Error("Missing approval controls")
        return renderCustomToolCallRow({
          activity,
          approvalDecision: bound,
          providerKey: "outlook_mail",
          compact: false,
          defaultOpen: true,
          live: false,
        })
      }
      vi.mocked(Button).mockClear()
      const html = renderToStaticMarkup(createElement(ApprovalProbe))
      assertReview(html)
      expect(html).toContain(bodyType === "html" ? "Reviewed HTML body" : snapshot.body)
      expect(html.includes("sandbox=")).toBe(bodyType === "html")
      click("Approve & Send")
      await vi.waitFor(() => {
        expect(submit).toHaveBeenCalledExactlyOnceWith(
          [{ tool_call_id: approval.tool_call_id, decision: "approved", override_args: null }],
          revision ?? undefined
        )
      })
      expect(approval.replay_args).toEqual({ message })
      expect(JSON.stringify(submit.mock.calls)).not.toContain("_draft")
      expect(JSON.stringify(submit.mock.calls)).not.toContain(snapshot.fingerprint)
    }
  )

  it("submits denial for the nested or direct call without executable arguments", async () => {
    const approval = pending(nested)
    const activity = project(approval, nested)
    const submit = vi.fn().mockResolvedValue(undefined)
    let bound = controls()
    function ApprovalProbe() {
      const resolver = useInlineApprovals({
        activeRunId: "active-run",
        approvalRevision: revision,
        approvals: [approval],
        enabled: true,
        isSubmitting: false,
        onSubmit: submit,
      })
      bound = resolver.resolveApprovalControls(activity) ?? controls()
      return null
    }
    renderToStaticMarkup(createElement(ApprovalProbe))
    bound.onDecisionChange({ decision: "denied", edits: {}, message: "Keep this draft" })
    await vi.waitFor(() => {
      expect(submit).toHaveBeenCalledExactlyOnceWith(
        [{ tool_call_id: approval.tool_call_id, decision: "denied", message: "Keep this draft" }],
        revision ?? undefined
      )
    })
    const html = render(
      activity,
      controls({ decision: { decision: "denied", edits: {}, message: "Keep this draft" } })
    )
    expect(html).toContain("Declined")
    assertReview(html)
  })

  it("keeps the review read-only after submission failure and on restored pending approval", async () => {
    const approval = pending(nested)
    const activity = project(approval, nested)
    const error = new Error("The request could not be submitted.")
    const submit = vi.fn().mockRejectedValue(error)
    let bound = controls()
    function ApprovalProbe() {
      const resolver = useInlineApprovals({
        activeRunId: "active-run",
        approvalRevision: revision,
        approvals: [approval],
        enabled: true,
        isSubmitting: false,
        onSubmit: submit,
      })
      bound = resolver.resolveApprovalControls(activity) ?? controls()
      return null
    }
    renderToStaticMarkup(createElement(ApprovalProbe))
    render(activity, bound)
    click("Approve & Send")
    await vi.waitFor(() => {
      expect(submit).toHaveBeenCalledExactlyOnceWith(
        [{ tool_call_id: approval.tool_call_id, decision: "approved", override_args: null }],
        revision ?? undefined
      )
    })
    await expect(submit.mock.results[0]?.value).rejects.toBe(error)
    const onDecisionChange = vi.fn()
    const failed = controls({
      decision: { decision: "approved", edits: {}, message: "" },
      error: error.message,
      onDecisionChange,
    })
    const html = render(activity, failed)
    assertReview(html)
    expect(html).toContain(failed.error)
    expect(html).toContain("Try Again")
    click("Try Again")
    expect(failed.onRetry).toHaveBeenCalledOnce()
    click("Decline")
    expect(onDecisionChange).toHaveBeenCalledWith({ decision: "pending", edits: {}, message: "" })
    const restored = render(project(approval, nested), controls())
    assertReview(restored)
    expect(restored).toContain("Requires Approval")
  })

  it("blocks a restored approval without review evidence", () => {
    const approval = pending(nested, null)
    const html = render(project(approval, nested), controls())
    expect(html).toContain("The draft could not be reviewed")
    const approve = vi
      .mocked(Button)
      .mock.calls.find(([props]) => props.children === "Approve & Send")
    expect(approve?.[0].disabled).toBe(true)
  })

  it.each([
    { _draft: { fingerprint: "b".repeat(64) } },
    { _draft: { subject: "Injected subject", body: "Injected body" } },
    { _draft: message },
    { _fingerprint: "b".repeat(64) },
  ])("rejects stale or injected display metadata edits %j", (edits) => {
    const approval = pending(nested)
    const result = buildResumeDecisions([approval], {
      [approval.tool_call_id]: { decision: "approved", edits, message: "" },
    })
    expect(result).toBe("This request can no longer be edited. Refresh and try again.")
  })

  it("keeps display metadata out of unchanged reference replay", () => {
    const approval = pending(nested)
    expect(
      buildResumeDecisions([approval], {
        [approval.tool_call_id]: { decision: "approved", edits: { message }, message: "" },
      })
    ).toEqual([{ tool_call_id: approval.tool_call_id, decision: "approved", override_args: null }])
  })
})
