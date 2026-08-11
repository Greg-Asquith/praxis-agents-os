// apps/web/src/features/conversations/approval-decisions.ts

import type { ApprovalDecision, ApprovalField } from "@/components/tool-ui/approval-card"
import { recordRowsValidity } from "@/components/tool-ui/records-field-values"
import type {
  EditedKeyValue,
  EditedRecords,
  EditedValue,
  EditedValues,
} from "@/components/tool-ui/edited-values"
import type { AgentRunResumeDecision, PendingToolApproval } from "@/features/conversations/types"
import { normalizeToolArgs } from "@/features/conversations/message-parts"
import { normalizeOptionalText } from "@/lib/format"
import { isRecord } from "@/lib/guards"

export type ApprovalDecisionMap = Record<string, ApprovalDecision>

export type ApprovalDecisionSummary = {
  allDecided: boolean
  approved: number
  denied: number
  pending: number
}

export const DEFAULT_APPROVAL_DECISION: ApprovalDecision = {
  decision: "pending",
  message: "",
  edits: {},
}

export function shouldSubmitDecisions(
  previous: ApprovalDecision,
  next: ApprovalDecision,
  summary: ApprovalDecisionSummary
): boolean {
  const isNewDecision = previous.decision === "pending" && next.decision !== "pending"
  return isNewDecision && summary.allDecided
}

export function buildResumeDecisions(
  approvals: PendingToolApproval[],
  decisions: ApprovalDecisionMap,
  fieldsForTool: (toolName: string) => ApprovalField[] | undefined = () => undefined
): AgentRunResumeDecision[] | string {
  const payload: AgentRunResumeDecision[] = []

  for (const approval of approvals) {
    const decision = decisions[approval.tool_call_id]
    const effectiveDecision = decision ?? DEFAULT_APPROVAL_DECISION

    if (effectiveDecision.decision === "pending") {
      return "Choose approve or decline for every tool request."
    }

    if (effectiveDecision.decision === "denied") {
      payload.push({
        decision: "denied",
        message: normalizeOptionalText(effectiveDecision.message),
        tool_call_id: approval.tool_call_id,
      })
      continue
    }

    const mergedArgs = buildMergedArgs(
      approval.args,
      approval.replay_args ?? approval.args,
      effectiveDecision.edits,
      fieldsForTool(approval.name)
    )
    if (typeof mergedArgs === "string") {
      return mergedArgs
    }

    payload.push({
      decision: "approved",
      override_args: mergedArgs,
      tool_call_id: approval.tool_call_id,
    })
  }

  return payload
}

export function summarizeApprovalDecisions(
  approvals: PendingToolApproval[],
  decisions: ApprovalDecisionMap
): ApprovalDecisionSummary {
  let pending = 0
  let approved = 0
  let denied = 0

  for (const approval of approvals) {
    const decision = decisions[approval.tool_call_id] ?? DEFAULT_APPROVAL_DECISION
    if (decision.decision === "approved") {
      approved += 1
    } else if (decision.decision === "denied") {
      denied += 1
    } else {
      pending += 1
    }
  }

  return {
    allDecided: approvals.length > 0 && pending === 0,
    approved,
    denied,
    pending,
  }
}

function buildMergedArgs(
  display: unknown,
  replay: unknown,
  edits: EditedValues,
  fields?: ApprovalField[]
): Record<string, unknown> | null | string {
  const editEntries = Object.entries(edits)
  if (editEntries.length === 0) {
    return null
  }

  const displayArgs = normalizeToolArgs(display)
  const replayArgs = normalizeToolArgs(replay)
  if (!isRecord(displayArgs) || !isRecord(replayArgs)) {
    return "This request can no longer be edited. Refresh and try again."
  }

  const changedEntries: [string, unknown][] = []
  const fieldsByKey = fields ? new Map(fields.map((field) => [field.key, field] as const)) : null
  for (const [key, edit] of editEntries) {
    const originalValue = displayArgs[key]
    const mergedEdit = mergeEditedValue(originalValue, edit, fieldsByKey?.get(key))
    if (mergedEdit === INVALID_EDIT) {
      return "This request can no longer be edited. Refresh and try again."
    }
    if (mergedEdit === NO_CHANGE) {
      continue
    }
    changedEntries.push([key, mergedEdit])
  }

  return changedEntries.length > 0 ? { ...replayArgs, ...Object.fromEntries(changedEntries) } : null
}

const NO_CHANGE = Symbol("no-change")
const INVALID_EDIT = Symbol("invalid-edit")

function mergeEditedValue(original: unknown, edit: EditedValue, field?: ApprovalField): unknown {
  if (field?.format === "records") {
    const validity = recordRowsValidity(edit, field.columns, field.min_rows)
    if (!validity.isRecords || validity.error !== null || !Array.isArray(original)) {
      return INVALID_EDIT
    }
    return structurallyEqual(edit, original) ? NO_CHANGE : edit
  }

  if (isEntityReference(edit)) {
    return structurallyEqual(edit, original) ? NO_CHANGE : edit
  }

  if (Array.isArray(edit) && edit.length > 0 && edit.every(isEntityReference)) {
    if (!Array.isArray(original)) {
      return INVALID_EDIT
    }
    return structurallyEqual(edit, original) ? NO_CHANGE : edit
  }

  if (isEditedRecords(edit)) {
    if (!recordRowsValidity(original, undefined, 1).isRecords) {
      return INVALID_EDIT
    }
    return structurallyEqual(edit, original) ? NO_CHANGE : edit
  }

  if (typeof edit === "string") {
    if (typeof original !== "string") {
      return INVALID_EDIT
    }
    const trimmedEdit = edit.trim()
    const trimmedOriginal = original.trim()
    return trimmedEdit === trimmedOriginal || (!trimmedEdit && trimmedOriginal)
      ? NO_CHANGE
      : trimmedEdit
  }

  if (typeof edit === "number") {
    if (
      typeof original !== "number" ||
      !Number.isFinite(original) ||
      !Number.isFinite(edit) ||
      (Number.isInteger(original) && !Number.isInteger(edit))
    ) {
      return INVALID_EDIT
    }
    return Object.is(edit, original) ? NO_CHANGE : edit
  }

  if (Array.isArray(edit)) {
    if (
      !Array.isArray(original) ||
      !original.every((item) => typeof item === "string") ||
      !edit.every((item) => typeof item === "string")
    ) {
      return INVALID_EDIT
    }
    return structurallyEqual(edit, original) ? NO_CHANGE : edit
  }

  if (!isRecord(original) || !isEditedKeyValue(edit)) {
    return INVALID_EDIT
  }
  const preservedComplexEntries = Object.entries(original).filter(
    ([, value]) => !isEditedScalar(value)
  )
  const merged = {
    ...dropEmptyAddedRows(original, edit),
    ...Object.fromEntries(preservedComplexEntries),
  }
  return structurallyEqual(merged, original) ? NO_CHANGE : merged
}

function dropEmptyAddedRows(
  original: Record<string, unknown>,
  edit: EditedKeyValue
): EditedKeyValue {
  return Object.fromEntries(
    Object.entries(edit).filter(
      ([key, value]) =>
        Object.hasOwn(original, key) || typeof value !== "string" || value.trim().length > 0
    )
  )
}

function isEditedKeyValue(value: EditedValue): value is EditedKeyValue {
  return isRecord(value) && Object.values(value).every((item) => isEditedScalar(item))
}

function isEditedRecords(value: EditedValue): value is EditedRecords {
  return recordRowsValidity(value, undefined, 1).isRecords
}

function isEditedScalar(value: unknown): value is string | number | boolean {
  return (
    typeof value === "string" ||
    typeof value === "boolean" ||
    (typeof value === "number" && Number.isFinite(value))
  )
}

function isEntityReference(value: unknown): value is Record<string, unknown> {
  return (
    isRecord(value) &&
    value["version"] === 1 &&
    typeof value["entity_kind"] === "string" &&
    typeof value["label"] === "string"
  )
}

function structurallyEqual(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) {
    return true
  }
  if (Array.isArray(left) && Array.isArray(right)) {
    return (
      left.length === right.length &&
      left.every((item, index) => structurallyEqual(item, right[index]))
    )
  }
  if (isRecord(left) && isRecord(right)) {
    const leftKeys = Object.keys(left)
    const rightKeys = Object.keys(right)
    return (
      leftKeys.length === rightKeys.length &&
      leftKeys.every((key) => Object.hasOwn(right, key) && structurallyEqual(left[key], right[key]))
    )
  }
  return false
}
