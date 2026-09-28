// Server-assigned approval identity; the approval ID defaults to the native tool call ID.
export function approvalIdentity(approvalId: string, ownerRunId = "run-1", rootRunId = ownerRunId) {
  return { approval_id: approvalId, owner_run_id: ownerRunId, root_run_id: rootRunId }
}
