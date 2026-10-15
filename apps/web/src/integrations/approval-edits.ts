// apps/web/src/integrations/approval-edits.ts

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-types"
import type { EditedValue } from "@/components/tool-ui/edited-values"

/** Applies several edits in one decision change; separate `onFieldEdit` calls in one handler overwrite each other. */
export function editApprovalFields(
  controls: ToolApprovalDecisionControls,
  disabled: boolean,
  edits: Record<string, EditedValue>
): void {
  if (disabled) return
  controls.onDecisionChange({
    decision: "pending",
    edits: { ...controls.decision.edits, ...edits },
    message: "",
  })
}
