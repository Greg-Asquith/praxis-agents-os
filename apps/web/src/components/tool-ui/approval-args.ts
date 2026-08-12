// apps/web/src/components/tool-ui/approval-args.ts

import { isRecord } from "@/lib/guards"

/** Return the current approval arguments after applying editable-field overrides. */
export function mergeApprovalArgs(args: unknown, edits: Record<string, unknown>): unknown {
  return isRecord(args) ? { ...args, ...edits } : args
}
