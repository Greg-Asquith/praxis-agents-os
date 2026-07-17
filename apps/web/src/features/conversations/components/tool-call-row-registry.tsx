// apps/web/src/features/conversations/components/tool-call-row-registry.tsx

import type { ReactNode } from "react"

import type { ToolApprovalDecisionControls } from "@/features/conversations/components/approval-decision-block"
import { DelegationToolRow } from "@/features/conversations/components/delegation-tool-row"
import { FileToolRow } from "@/features/conversations/components/file-tool-row"
import { SkillActivationRow } from "@/features/conversations/components/skill-activation-row"
import { SkillDocumentReadRow } from "@/features/conversations/components/skill-document-read-row"
import { TodoListRow } from "@/features/conversations/components/todo-list-row"
import {
  LIST_FILES_TOOL_NAME,
  PROMOTE_SCRATCH_TOOL_NAME,
  READ_FILE_TOOL_NAME,
  WRITE_FILE_TOOL_NAME,
  listFilesResult,
  promoteScratchResult,
  readFileContentResult,
  readFileImageResult,
  readFileStatusResult,
  readFileUrlResult,
  writeFileResult,
} from "@/features/conversations/file-tools"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  LOAD_CAPABILITY_TOOL_NAME,
  skillIdFromCapabilityArgs,
} from "@/features/conversations/skill-activation"
import { READ_SKILL_DOCUMENT_TOOL_NAME } from "@/features/conversations/skill-document-read"
import { isTodoToolActivity, todoItemsFromActivity } from "@/features/conversations/todo-tools"

// Tool rows resolve in three layers: a custom presenter registered here wins,
// otherwise the default row renders from the tool's server-declared presentation
// (/tools/presentations), otherwise from generic verb + label fallbacks.
// Register a presenter only when a tool needs richer UI than the declarative
// config can express; everything else should be configured on its backend
// runtime_tool definition.

type ToolRowPresenterProps = {
  activity: ToolActivity
  approvalDecision?: ToolApprovalDecisionControls
  compact: boolean
  defaultOpen: boolean
  live: boolean
}

type ToolRowPresenter = {
  key: string
  matches: (activity: ToolActivity) => boolean
  render: (props: ToolRowPresenterProps) => ReactNode
}

const TOOL_ROW_PRESENTERS: ToolRowPresenter[] = [
  {
    key: "delegation",
    matches: (activity) => Boolean(activity.delegate),
    render: ({ activity, approvalDecision, compact, defaultOpen, live }) => (
      <DelegationToolRow
        activity={activity}
        {...(approvalDecision ? { approvalDecision } : {})}
        compact={compact}
        defaultOpen={defaultOpen}
        live={live}
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
  {
    key: "todo-list",
    matches: (activity) => isTodoToolActivity(activity) && todoItemsFromActivity(activity) !== null,
    render: ({ activity, compact }) => <TodoListRow activity={activity} compact={compact} />,
  },
  {
    key: "file-tools",
    matches: fileToolRowMatches,
    render: ({ activity, compact, defaultOpen }) => (
      <FileToolRow activity={activity} compact={compact} defaultOpen={defaultOpen} />
    ),
  },
]

export function renderCustomToolCallRow(props: ToolRowPresenterProps) {
  const presenter = TOOL_ROW_PRESENTERS.find((item) => item.matches(props.activity))
  return presenter ? presenter.render(props) : null
}

function fileToolRowMatches(activity: ToolActivity) {
  if (activity.name === LIST_FILES_TOOL_NAME) {
    return listFilesResult(activity.result) !== null
  }
  if (activity.name === WRITE_FILE_TOOL_NAME) {
    return writeFileResult(activity.result) !== null
  }
  if (activity.name === PROMOTE_SCRATCH_TOOL_NAME) {
    return promoteScratchResult(activity.result) !== null
  }
  if (activity.name === READ_FILE_TOOL_NAME) {
    return (
      readFileUrlResult(activity.result) !== null ||
      readFileContentResult(activity.result) !== null ||
      readFileStatusResult(activity.result) !== null ||
      readFileImageResult(activity.result) !== null
    )
  }
  return false
}
