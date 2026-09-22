import type * as ReactModule from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { useInlineApprovals } from "@/features/conversations/hooks/use-inline-approvals"
import type { PendingToolApproval } from "@/features/conversations/types"
import type { ToolActivity } from "@/features/conversations/message-parts"
import type { ToolPresentationEntry } from "@/features/tools/types"

const state = vi.hoisted(() => ({ slots: [] as unknown[], cursor: 0 }))
vi.mock("react", async (original) => ({
  ...(await original<typeof ReactModule>()),
  useState: (initial: unknown) => {
    const index = state.cursor++
    if (state.slots.length <= index) state.slots[index] = initial
    return [
      state.slots[index],
      (value: unknown) => {
        state.slots[index] = value
      },
    ]
  },
  useRef: (initial: unknown) => {
    const index = state.cursor++
    if (state.slots.length <= index) state.slots[index] = { current: initial }
    return state.slots[index]
  },
  useMemo: (factory: () => unknown) => factory(),
  useLayoutEffect: (effect: () => void) => {
    effect()
  },
}))
const originalSource = {
  version: 1,
  entity_kind: "file",
  entity_id: "original-file",
  label: "Original file",
}
const selectedSource = { ...originalSource, entity_id: "selected-file", label: "Selected file" }
const replay = { source: originalSource, name: "Report.xlsx", content: null }
const approval: PendingToolApproval = {
  approval_id: "approval-leaf",
  tool_call_id: "native-call",
  owner_run_id: "root",
  name: "sharepoint_write_file",
  args: {
    ...replay,
    _source: { revision_id: "private-initial-pin", size_bytes: 2048 },
    _source_review_required: false,
  },
  replay_args: replay,
}
const activity: ToolActivity = {
  id: "native-call",
  approvalId: "approval-leaf",
  agentRunId: "root",
  kind: "approval",
  status: "awaiting_approval",
  name: "sharepoint_write_file",
  args: approval.args,
}
const presentation: ToolPresentationEntry = {
  name: "sharepoint_write_file",
  provider: "sharepoint",
  label: "Save file",
  effect: "write",
  ui: {
    icon: "sharepoint",
    running_label: "Saving",
    completed_label: "Saved",
    failed_label: "Failed",
    approval_title: "Save file",
    approval_prompt: "Review file",
    approve_label: "Approve",
    result_fields: [],
    arg_fields: [
      {
        key: "source",
        label: "Source",
        format: "entity",
        editable: true,
        secondary: true,
        entity_kind: "file",
        min_rows: 0,
        placeholder: "",
        options: [],
      },
    ],
  },
}
const onReview = vi.fn<(input: unknown) => Promise<void>>()
const onSubmit = vi.fn<() => Promise<void>>()
type Params = Parameters<typeof useInlineApprovals>[0]
function ApprovalProbe(params: Params) {
  return useInlineApprovals(params)
}
function render(overrides: Partial<Params> = {}, target = activity) {
  const params: Params = {
    activeRunId: "root",
    approvalRevision: "round-1",
    approvals: [approval],
    enabled: true,
    isSubmitting: false,
    onSubmit,
    onReview,
    presentationFor: () => presentation,
    ...overrides,
  }
  state.cursor = 0
  ApprovalProbe(params)
  state.cursor = 0
  return ApprovalProbe(params).resolveApprovalControls(target)
}
function editSource(overrides: Partial<Params> = {}, target = activity) {
  render(overrides, target)?.onDecisionChange({
    decision: "pending",
    message: "",
    edits: { source: selectedSource },
  })
  return render(overrides, target)
}
beforeEach(() => {
  state.slots = []
  state.cursor = 0
  onReview.mockReset().mockResolvedValue(undefined)
  onSubmit.mockReset().mockResolvedValue(undefined)
})
describe("approval File re-review interactions", () => {
  it.each([
    ["direct", "root", "native-call"],
    ["nested", "root", "workflow/nested-call"],
    ["delegated", "child", "native-call"],
  ])(
    "reviews %s approval by leaf identity through the owning root",
    async (_kind, owner, callId) => {
      const pending = { ...approval, owner_run_id: owner, tool_call_id: callId }
      const target = { ...activity, agentRunId: owner, rootRunId: "root", id: callId }
      editSource({ approvals: [pending] }, target)?.onReview?.()
      expect(onReview).toHaveBeenCalledExactlyOnceWith({
        runId: "root",
        approval_revision: "round-1",
        approval_id: "approval-leaf",
        override_args: { ...replay, source: selectedSource },
      })
      expect(JSON.stringify(onReview.mock.calls)).not.toMatch(
        /private-initial-pin|_source|revision_id/
      )
      expect(onSubmit).not.toHaveBeenCalled()
      await Promise.resolve()
    }
  )
  it("uses executable replay arguments when there are no edits", () => {
    render()?.onReview?.()
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ override_args: replay }))
  })
  it("rejects attempts to submit display-only pin metadata", () => {
    render()?.onDecisionChange({
      decision: "pending",
      message: "",
      edits: { _source: "injected pin" },
    })
    render()?.onReview?.()
    expect(onReview).not.toHaveBeenCalled()
    expect(render()?.error).toContain("can no longer be edited")
  })
  it.each([null, "invalid", undefined])(
    "rejects edited source review without executable replay arguments: %j",
    (replayArgs) => {
      const { replay_args: _replayArgs, ...withoutReplay } = approval
      const pending =
        replayArgs === undefined ? withoutReplay : { ...approval, replay_args: replayArgs }
      editSource({ approvals: [pending] })?.onReview?.()
      expect(onReview).not.toHaveBeenCalled()
    }
  )
  it("rejects the wrong owner or submission root", () => {
    expect(render({}, { ...activity, agentRunId: "other" })).toBeNull()
    expect(render({}, { ...activity, rootRunId: "other" })).toBeNull()
  })
  it.each([{ readOnly: true }, { enabled: false }])("provides no controls for %j", (overrides) => {
    expect(render(overrides)).toBeNull()
    expect(onReview).not.toHaveBeenCalled()
  })
  it.each([{ activeRunId: "other" }, { approvalRevision: "round-2" }])(
    "blocks retained callbacks after scope changes to %j",
    (overrides) => {
      const retained = editSource()
      render(overrides)
      retained?.onReview?.()
      expect(onReview).not.toHaveBeenCalled()
    }
  )
  it.each([{ readOnly: true }, { enabled: false }, { isSubmitting: true }])(
    "blocks a retained callback when availability changes to %j",
    (overrides) => {
      const retained = editSource()
      render(overrides)
      retained?.onReview?.()
      expect(onReview).not.toHaveBeenCalled()
    }
  )
  it("blocks duplicate review, approval, and edits while review is in flight", async () => {
    let finish: () => void = () => undefined
    onReview.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve
        })
    )
    const controls = editSource()
    controls?.onReview?.()
    controls?.onReview?.()
    controls?.onDecisionChange({ decision: "approved", message: "", edits: {} })
    controls?.onRetry()
    const pending = render()
    expect(pending?.disabled).toBe(true)
    expect(pending?.submitting).toBe(true)
    expect(onReview).toHaveBeenCalledOnce()
    expect(onSubmit).not.toHaveBeenCalled()
    finish()
    await Promise.resolve()
    expect(render()?.disabled).toBe(false)
  })
  it("keeps failed review edits and exposes the failure for retry", async () => {
    onReview.mockRejectedValue(new Error("Choose a File you can access."))
    editSource()?.onReview?.()
    await Promise.resolve()
    const failed = render()
    expect(failed?.error).toBe("Choose a File you can access.")
    expect(failed?.decision.edits).toEqual({ source: selectedSource })
    expect(failed?.disabled).toBe(false)
    onReview.mockResolvedValue(undefined)
    failed?.onRetry()
    expect(onReview).toHaveBeenCalledTimes(2)
    expect(onSubmit).not.toHaveBeenCalled()
  })
  it("does not publish an old review failure into a refreshed proposal", async () => {
    let reject: (error: Error) => void = () => undefined
    onReview.mockImplementation(
      () =>
        new Promise<void>((_resolve, fail) => {
          reject = fail
        })
    )
    editSource()?.onReview?.()
    render({ approvalRevision: "round-2" })
    reject(new Error("Old review failed"))
    await Promise.resolve()
    expect(render({ approvalRevision: "round-2" })?.error).toBeNull()
  })
  it.each([
    { isSubmitting: true },
    { approvalRevision: null },
    { approvals: [approval, approval] },
  ])("does not review an unavailable approval: %j", (overrides) => {
    render(overrides)?.onReview?.()
    expect(onReview).not.toHaveBeenCalled()
  })
})
