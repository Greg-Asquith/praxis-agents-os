// apps/web/src/components/tool-ui/approval-args.ts

import { isRecord } from "@/lib/guards"

const APPROVAL_DISPLAY_ERROR =
  "Approval details are unavailable. Decline this request, then ask the agent to prepare the action again."

/** Return the current approval arguments after applying editable-field overrides. */
export function mergeApprovalArgs(args: unknown, edits: Record<string, unknown>): unknown {
  return isRecord(args) ? { ...args, ...edits } : args
}

/** Return a fail-closed message when server-owned approval presentation failed. */
export function approvalDisplayError(args: unknown): string | null {
  return isRecord(args) && typeof args["_approval_display_error"] === "string"
    ? APPROVAL_DISPLAY_ERROR
    : null
}
