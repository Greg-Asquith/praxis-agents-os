// apps/web/src/features/conversations/components/memory-tool-presenter.tsx

import { MemoryToolRow } from "@/features/conversations/components/memory-tool-row"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  FORGET_MEMORY_TOOL_NAME,
  SAVE_MEMORY_TOOL_NAME,
  SEARCH_MEMORY_TOOL_NAME,
  UPDATE_MEMORY_TOOL_NAME,
  forgetMemoryResult,
  saveMemoryResult,
  searchMemoryResult,
  updateMemoryResult,
} from "@/features/conversations/native-tools/memory-tools"
import type { ToolRowPresenter } from "@/integrations/contract"

export const memoryToolPresenter: ToolRowPresenter = {
  handlesApprovals: true,
  key: "memory-tools",
  matches: memoryToolRowMatches,
  render: ({ activity, approvalDecision, defaultOpen, label, ui }) => (
    <MemoryToolRow
      activity={activity}
      {...(approvalDecision ? { approvalDecision } : {})}
      defaultOpen={defaultOpen}
      label={label ?? activity.name}
      ui={ui ?? null}
    />
  ),
}

function memoryToolRowMatches(activity: ToolActivity) {
  if (
    (activity.name === SAVE_MEMORY_TOOL_NAME ||
      activity.name === SEARCH_MEMORY_TOOL_NAME ||
      activity.name === UPDATE_MEMORY_TOOL_NAME ||
      activity.name === FORGET_MEMORY_TOOL_NAME) &&
    activity.status !== "completed"
  ) {
    return true
  }
  if (activity.name === SAVE_MEMORY_TOOL_NAME) {
    return saveMemoryResult(activity.result) !== null
  }
  if (activity.name === SEARCH_MEMORY_TOOL_NAME) {
    return searchMemoryResult(activity.result) !== null
  }
  if (activity.name === UPDATE_MEMORY_TOOL_NAME) {
    return updateMemoryResult(activity.result) !== null
  }
  if (activity.name === FORGET_MEMORY_TOOL_NAME) {
    return forgetMemoryResult(activity.result) !== null
  }
  return false
}
