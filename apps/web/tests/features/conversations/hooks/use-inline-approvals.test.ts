import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { approvalBatchIsReady } from "@/features/conversations/approval-decisions"
import {
  agentStreamReducer,
  initialAgentStreamState,
  type AgentStreamState,
} from "@/features/conversations/stream/reducer"
import { useInlineApprovals } from "@/features/conversations/hooks/use-inline-approvals"
import type { ToolActivity } from "@/features/conversations/message-parts"
import type { PendingToolApproval } from "@/features/conversations/types"

const approvals: PendingToolApproval[] = [
  {
    tool_call_id: "reused-call",
    name: "write_file",
    args: { name: "active.txt" },
  },
]

describe("useInlineApprovals", () => {
  it("only binds approval controls to the matching active run", () => {
    const html = renderToStaticMarkup(createElement(ApprovalBindingProbe))

    expect(html).toContain('data-active="bound"')
    expect(html).toContain('data-old="unbound"')
  })
})

function ApprovalBindingProbe() {
  const { resolveApprovalControls } = useInlineApprovals({
    activeRunId: "run-active",
    approvals,
    enabled: true,
    isSubmitting: false,
    onSubmit: () => Promise.resolve(),
  })

  const oldActivity = approvalActivity("run-old")
  const activeActivity = approvalActivity("run-active")

  return createElement("span", {
    "data-active": resolveApprovalControls(activeActivity) ? "bound" : "unbound",
    "data-old": resolveApprovalControls(oldActivity) ? "bound" : "unbound",
  })
}

function approvalActivity(agentRunId: string): ToolActivity {
  return {
    id: "reused-call",
    agentRunId,
    kind: "approval",
    status: "awaiting_approval",
    name: "write_file",
    args: { name: `${agentRunId}.txt` },
  }
}

it("binds siblings to their owner and explicit submission root", () => {
  function Probe() {
    const siblings = ["a", "b"].map((owner): PendingToolApproval => ({
      tool_call_id: "same",
      owner_run_id: owner,
      approval_id: `approval-${owner}`,
      name: "write_file",
      args: {},
    }))
    const { resolveApprovalControls } = useInlineApprovals({
      activeRunId: "root",
      approvalRevision: "round-1",
      approvals: siblings,
      enabled: true,
      isSubmitting: false,
      onSubmit: () => Promise.resolve(),
    })
    const activity = {
      ...approvalActivity("a"),
      id: "same",
      rootRunId: "root",
      approvalId: "approval-a",
    }
    return createElement("span", {
      "data-a": Boolean(resolveApprovalControls(activity)),
      "data-b": Boolean(
        resolveApprovalControls({ ...activity, agentRunId: "b", approvalId: "approval-b" })
      ),
      "data-wrong-owner": Boolean(resolveApprovalControls({ ...activity, agentRunId: "b" })),
    })
  }
  const html = renderToStaticMarkup(createElement(Probe))
  expect(html).toContain('data-a="true"')
  expect(html).toContain('data-b="true"')
  expect(html).toContain('data-wrong-owner="false"')
})

it("exposes no approval controls in a delegated transcript", () => {
  function Probe() {
    const { resolveApprovalControls } = useInlineApprovals({
      activeRunId: "run-active",
      approvals,
      enabled: true,
      readOnly: true,
      isSubmitting: false,
      onSubmit: () => Promise.resolve(),
    })
    return createElement("span", {
      "data-bound": Boolean(resolveApprovalControls(approvalActivity("run-active"))),
    })
  }
  expect(renderToStaticMarkup(createElement(Probe))).toContain('data-bound="false"')
})

it("remounts editor state when the proposal revision changes while the leaf ID stays identical", () => {
  function Probe({ revision }: { revision: string }) {
    const { resolveApprovalControls } = useInlineApprovals({
      activeRunId: "root",
      approvalRevision: revision,
      approvals: [
        { approval_id: "stable-leaf", tool_call_id: "reused-call", name: "write_file", args: {} },
      ],
      enabled: true,
      isSubmitting: false,
      onSubmit: () => Promise.resolve(),
    })
    const controls = resolveApprovalControls({
      ...approvalActivity("root"),
      approvalId: "stable-leaf",
    })
    return createElement("span", { "data-editor-key": controls?.formKey })
  }
  const first = renderToStaticMarkup(createElement(Probe, { revision: "proposal-a" }))
  const second = renderToStaticMarkup(createElement(Probe, { revision: "proposal-b" }))
  expect(first).not.toBe(second)
  expect(first).toContain("proposal-a")
  expect(second).toContain("proposal-b")
})

it("keeps sequential streamed siblings unavailable until done or a complete matching REST batch", () => {
  function Probe({ state, recovered = false }: { state: AgentStreamState; recovered?: boolean }) {
    const { resolveApprovalControls } = useInlineApprovals({
      activeRunId: "root",
      approvalRevision: "round",
      approvals: Object.values(state.approvals),
      enabled: approvalBatchIsReady({
        currentRevision: "round",
        proposalRevision: state.approvalRevision,
        hasRecoveredBatch: recovered,
        streamBatchComplete: state.approvalBatchComplete,
      }),
      isSubmitting: false,
      onSubmit: () => Promise.resolve(),
    })
    return createElement("span", {
      "data-can-approve": Boolean(
        resolveApprovalControls({
          ...approvalActivity("child-a"),
          rootRunId: "root",
          id: "native",
          approvalId: "approval-child-a",
        })
      ),
    })
  }
  const frame = (owner: string, seq: number) => ({
    type: "event" as const,
    event: {
      event: "tool.approval_required" as const,
      data: {
        run_id: "root",
        conversation_id: "conversation",
        seq,
        tool_call_id: "native",
        owner_run_id: owner,
        approval_id: `approval-${owner}`,
        approval_revision: "round",
        name: "write_file",
        args: {},
      },
    },
  })
  const first = agentStreamReducer(initialAgentStreamState, frame("child-a", 1))
  const second = agentStreamReducer(first, frame("child-b", 2))
  for (const state of [
    first,
    second,
    agentStreamReducer(second, { type: "abort" }),
    agentStreamReducer(second, { type: "finishClosedStream" }),
  ]) {
    expect(renderToStaticMarkup(createElement(Probe, { state }))).toContain(
      'data-can-approve="false"'
    )
  }
  const complete = agentStreamReducer(second, {
    type: "event",
    event: {
      event: "done",
      data: {
        run_id: "root",
        conversation_id: "conversation",
        seq: 3,
        status: "awaiting_approval",
      },
    },
  })
  expect(renderToStaticMarkup(createElement(Probe, { state: complete }))).toContain(
    'data-can-approve="true"'
  )
  expect(
    renderToStaticMarkup(
      createElement(Probe, {
        state: agentStreamReducer(second, { type: "abort" }),
        recovered: true,
      })
    )
  ).toContain('data-can-approve="true"')
})
