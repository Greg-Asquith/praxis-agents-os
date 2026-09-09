import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { createQueryClient } from "@/app/query-client"
import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-card"
import { conversationRecoveryQueryOptions } from "@/features/conversations/api/get-conversation-recovery"
import { resumeRunStream } from "@/features/conversations/api/resume-run-stream"
import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import { reconcileApprovalSubmission } from "@/features/conversations/approval-submission"
import { useInlineApprovals } from "@/features/conversations/hooks/use-inline-approvals"
import { parseApiError } from "@/lib/api/errors"
import { setActiveUserId, setActiveWorkspaceSlug } from "@/lib/workspace"
import { jsonResponse, stubFetch } from "../../support/fetch-stub"

const revision = "a".repeat(64)

describe("approval submission recovery", () => {
  let client: ReturnType<typeof createQueryClient>
  beforeEach(() => {
    vi.useFakeTimers()
    client = createQueryClient()
    setActiveUserId("user")
    setActiveWorkspaceSlug("workspace")
  })
  afterEach(() => {
    client.clear()
    setActiveUserId(null)
    setActiveWorkspaceSlug(null)
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it.each(["lost", "approval_already_reserved", "approval_decisions_conflict"])(
    "keeps the card Retry behind reconciliation after %s, with one POST",
    async (outcome) => {
      let finishRead: (() => void) | undefined
      let settled = false
      const fetch = stubFetch((input, init) => {
        if (init?.method === "POST") {
          if (outcome === "lost") throw new TypeError("Failed to fetch")
          return jsonResponse({ code: outcome }, { status: 409 })
        }
        if ((input instanceof Request ? input.url : input.toString()).endsWith("active-run")) {
          return new Promise((resolve) => {
            finishRead = () => {
              resolve(
                jsonResponse({
                  active_run: null,
                  latest_run: { id: "root", status: "completed" },
                  approval_expires_at: null,
                })
              )
            }
          })
        }
        return jsonResponse({ messages: [], total: 0 })
      })
      let controls: ToolApprovalDecisionControls | null = null
      function Probe() {
        const { resolveApprovalControls } = useInlineApprovals({
          activeRunId: "root",
          approvalRevision: revision,
          approvals: [
            { approval_id: "leaf", tool_call_id: "native", name: "write_file", args: {} },
          ],
          enabled: true,
          isSubmitting: false,
          onSubmit: (decisions) =>
            reconcileApprovalSubmission(
              async () => {
                const response = await resumeRunStream({
                  runId: "root",
                  payload: { decisions, approval_revision: revision },
                })
                if (!response.ok) throw await parseApiError(response)
              },
              () =>
                client.fetchQuery({
                  ...conversationRecoveryQueryOptions(client, "conversation"),
                  staleTime: 0,
                })
            ).finally(() => {
              settled = true
            }),
        })
        controls = resolveApprovalControls({
          id: "native",
          approvalId: "leaf",
          agentRunId: "root",
          kind: "approval",
          status: "awaiting_approval",
          name: "write_file",
          args: {},
        })
        return null
      }
      renderToStaticMarkup(createElement(Probe))
      const card = controls as ToolApprovalDecisionControls | null
      expect(card).not.toBeNull()
      card?.onDecisionChange({ decision: "approved", message: "", edits: {} })
      await vi.advanceTimersByTimeAsync(0)
      expect(settled).toBe(false)
      card?.onRetry()
      card?.onDecisionChange({ decision: "denied", message: "Changed my decision", edits: {} })
      await vi.advanceTimersByTimeAsync(0)
      expect(fetch.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1)
      finishRead?.()
      await vi.advanceTimersByTimeAsync(0)
      expect(settled).toBe(true)
      expect(client.getQueryData(conversationsQueryKeys.activeRun("conversation"))).toMatchObject({
        active_run: null,
        latest_run: { status: "completed" },
      })
      expect(fetch.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1)
      expect(
        fetch.mock.calls.filter(([input]) =>
          (input instanceof Request ? input.url : input.toString()).endsWith("approval-state")
        )
      ).toHaveLength(0)
    }
  )

  it("refreshes once after a successful submission and propagates a read failure", async () => {
    const submit = vi.fn().mockResolvedValue(undefined)
    const refresh = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"))
    await expect(reconcileApprovalSubmission(submit, refresh)).rejects.toThrow("Failed to fetch")
    expect(submit).toHaveBeenCalledOnce()
    expect(refresh).toHaveBeenCalledOnce()
  })

  it("blocks retained card callbacks while the route is reconciling", () => {
    const submit = vi.fn().mockResolvedValue(undefined)
    let controls: ToolApprovalDecisionControls | null = null
    function Probe() {
      const { resolveApprovalControls } = useInlineApprovals({
        activeRunId: "root",
        approvalRevision: revision,
        approvals: [{ tool_call_id: "native", name: "write_file", args: {} }],
        enabled: true,
        isSubmitting: true,
        onSubmit: submit,
      })
      controls = resolveApprovalControls({
        id: "native",
        agentRunId: "root",
        kind: "approval",
        status: "awaiting_approval",
        name: "write_file",
        args: {},
      })
      return null
    }
    renderToStaticMarkup(createElement(Probe))
    const card = controls as ToolApprovalDecisionControls | null
    expect(card?.disabled).toBe(true)
    card?.onRetry()
    card?.onDecisionChange({ decision: "approved", message: "", edits: {} })
    expect(submit).not.toHaveBeenCalled()
  })
})
