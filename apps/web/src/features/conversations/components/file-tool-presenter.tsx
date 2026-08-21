// apps/web/src/features/conversations/components/file-tool-presenter.tsx

import { FileToolRow } from "@/features/conversations/components/file-tool-row"
import {
  generateImageResult,
  isImageOutputTool,
  listFilesResult,
  LIST_FILES_TOOL_NAME,
  readFileContentResult,
  readFileImageResult,
  readFileStatusResult,
  READ_FILE_TOOL_NAME,
  readFileUrlResult,
  writeFileResult,
  WRITE_FILE_TOOL_NAME,
} from "@/features/conversations/native-tools/file-tools"
import type { ToolActivity } from "@/features/conversations/message-parts"
import type { ToolRowPresenter } from "@/integrations/contract"

export const fileToolPresenter: ToolRowPresenter = {
  handlesApprovals: true,
  key: "file-tools",
  matches: fileToolRowMatches,
  render: ({ activity, approvalDecision, defaultOpen, label, ui }) => (
    <FileToolRow
      activity={activity}
      {...(approvalDecision ? { approvalDecision } : {})}
      defaultOpen={defaultOpen}
      label={label ?? activity.name}
      ui={ui ?? null}
    />
  ),
}

function fileToolRowMatches(activity: ToolActivity) {
  if (
    (activity.name === LIST_FILES_TOOL_NAME ||
      isImageOutputTool(activity.name) ||
      activity.name === WRITE_FILE_TOOL_NAME ||
      activity.name === READ_FILE_TOOL_NAME) &&
    activity.status !== "completed"
  ) {
    return true
  }
  if (activity.name === LIST_FILES_TOOL_NAME) {
    return listFilesResult(activity.result) !== null
  }
  if (isImageOutputTool(activity.name)) {
    return generateImageResult(activity.result) !== null
  }
  if (activity.name === WRITE_FILE_TOOL_NAME) {
    return writeFileResult(activity.result) !== null
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
