// apps/web/src/components/tool-ui/approval-types.ts

import type { EditedValues } from "@/components/tool-ui/edited-values"
import type { ResolvedToolField, ToolFieldFormat } from "@/components/tool-ui/field-resolution"

export type ApprovalDecision =
  | { decision: "pending"; edits: EditedValues; message: "" }
  | { decision: "approved"; edits: EditedValues; message: "" }
  | { decision: "denied"; edits: EditedValues; message: string }

export type ToolApprovalDecisionControls = {
  decision: ApprovalDecision
  disabled?: boolean
  error: string | null
  onDecisionChange: (decision: ApprovalDecision) => void
  onRetry: () => void
  pendingCount: number
  submitting: boolean
}

export type ApprovalField = {
  editable: boolean
  format: ToolFieldFormat
  key: string
  label: string
  options: string[]
  placeholder: string
  secondary: boolean
}

export type ApprovalFallbackField = ResolvedToolField
