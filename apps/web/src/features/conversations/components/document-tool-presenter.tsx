// apps/web/src/features/conversations/components/document-tool-presenter.tsx

import { DocumentToolRow } from "@/features/conversations/components/document-tool-row"
import {
  documentToolResult,
  isDocumentToolName,
} from "@/features/conversations/native-tools/document-tools"
import type { ToolActivity } from "@/features/conversations/message-parts"
import type { ToolRowPresenter } from "@/integrations/contract"

export const documentToolPresenter: ToolRowPresenter = {
  handlesApprovals: true,
  key: "document-tools",
  matches: documentToolRowMatches,
  render: ({ activity, approvalDecision, defaultOpen, label, ui }) => (
    <DocumentToolRow
      activity={activity}
      {...(approvalDecision ? { approvalDecision } : {})}
      defaultOpen={defaultOpen}
      label={label ?? activity.name}
      ui={ui ?? null}
    />
  ),
}

function documentToolRowMatches(activity: ToolActivity) {
  if (!isDocumentToolName(activity.name) || activity.status === "unknown") return false
  if (activity.status !== "completed") return true
  return documentToolResult(activity.name, activity.result) !== null
}
