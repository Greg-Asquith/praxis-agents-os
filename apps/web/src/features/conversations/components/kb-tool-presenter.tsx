// apps/web/src/features/conversations/components/kb-tool-presenter.tsx

import { KbToolRow } from "@/features/conversations/components/kb-tool-row"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  READ_DOCUMENT_TOOL_NAME,
  SEARCH_KNOWLEDGE_TOOL_NAME,
  readDocumentResult,
  searchKnowledgeResult,
} from "@/features/conversations/native-tools/kb-tools"
import type { ToolRowPresenter } from "@/integrations/contract"

export const kbToolPresenter: ToolRowPresenter = {
  key: "kb-tools",
  matches: kbToolRowMatches,
  render: ({ activity, defaultOpen }) => (
    <KbToolRow activity={activity} defaultOpen={defaultOpen} />
  ),
}

function kbToolRowMatches(activity: ToolActivity) {
  if (
    (activity.name === SEARCH_KNOWLEDGE_TOOL_NAME || activity.name === READ_DOCUMENT_TOOL_NAME) &&
    activity.status !== "completed"
  ) {
    return true
  }
  if (activity.name === SEARCH_KNOWLEDGE_TOOL_NAME) {
    return searchKnowledgeResult(activity.result) !== null
  }
  if (activity.name === READ_DOCUMENT_TOOL_NAME) {
    return readDocumentResult(activity.result) !== null
  }
  return false
}
