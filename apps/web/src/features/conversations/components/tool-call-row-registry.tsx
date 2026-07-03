// apps/web/src/features/conversations/components/tool-call-row-registry.tsx

import type { ReactNode } from "react"

import type { ToolApprovalDecisionControls } from "@/features/conversations/components/approval-decision-block"
import { DelegationToolRow } from "@/features/conversations/components/delegation-tool-row"
import { SkillActivationRow } from "@/features/conversations/components/skill-activation-row"
import { SkillDocumentReadRow } from "@/features/conversations/components/skill-document-read-row"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  LOAD_CAPABILITY_TOOL_NAME,
  skillIdFromCapabilityArgs,
} from "@/features/conversations/skill-activation"
import { READ_SKILL_DOCUMENT_TOOL_NAME } from "@/features/conversations/skill-document-read"

type ToolCallRowRenderProps = {
  activity: ToolActivity
  approvalDecision?: ToolApprovalDecisionControls
  compact: boolean
  defaultOpen: boolean
}

type ToolCallRowDefinition = {
  key: string
  matches: (activity: ToolActivity) => boolean
  render: (props: ToolCallRowRenderProps) => ReactNode
}

const TOOL_CALL_ROW_DEFINITIONS: ToolCallRowDefinition[] = [
  {
    key: "delegation",
    matches: (activity) => Boolean(activity.delegate),
    render: ({ activity, approvalDecision, compact, defaultOpen }) => (
      <DelegationToolRow
        activity={activity}
        {...(approvalDecision ? { approvalDecision } : {})}
        compact={compact}
        defaultOpen={defaultOpen}
      />
    ),
  },
  {
    key: "skill-activation",
    matches: (activity) =>
      (activity.toolKind === "capability-load" || activity.name === LOAD_CAPABILITY_TOOL_NAME) &&
      skillIdFromCapabilityArgs(activity.args) !== null,
    render: ({ activity, compact }) => <SkillActivationRow activity={activity} compact={compact} />,
  },
  {
    key: "skill-document-read",
    matches: (activity) => activity.name === READ_SKILL_DOCUMENT_TOOL_NAME,
    render: ({ activity, compact, defaultOpen }) => (
      <SkillDocumentReadRow activity={activity} compact={compact} defaultOpen={defaultOpen} />
    ),
  },
]

export function renderCustomToolCallRow(props: ToolCallRowRenderProps) {
  const definition = TOOL_CALL_ROW_DEFINITIONS.find((item) => item.matches(props.activity))
  return definition ? definition.render(props) : null
}
