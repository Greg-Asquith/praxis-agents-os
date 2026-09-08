// apps/web/src/features/conversations/approval-submission.ts

import { approvalConflictMessage } from "@/features/conversations/run-error-copy"

export async function reconcileApprovalSubmission(
  submit: () => Promise<unknown>,
  refresh: () => Promise<unknown>
) {
  try {
    await submit()
  } catch (error) {
    // An uncertain response cannot permit another decision until the reads settle.
    await refresh().catch(() => undefined)
    const message = approvalConflictMessage(error)
    if (message) throw new Error(message, { cause: error })
    throw error
  }
  await refresh()
}
