// apps/web/src/features/conversations/components/artifact-tool-presenter.tsx

import { ArtifactToolRow } from "@/features/conversations/components/artifact-tool-row"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  CREATE_ARTIFACT_TOOL_NAME,
  LIST_ARTIFACTS_TOOL_NAME,
  READ_ARTIFACT_TOOL_NAME,
  UPDATE_ARTIFACT_TOOL_NAME,
  artifactListToolResult,
  artifactReadToolResult,
  artifactToolResult,
} from "@/features/conversations/native-tools/artifact-tools"
import type { ToolRowPresenter } from "@/integrations/contract"

const ARTIFACT_TOOL_NAMES = new Set([
  CREATE_ARTIFACT_TOOL_NAME,
  LIST_ARTIFACTS_TOOL_NAME,
  READ_ARTIFACT_TOOL_NAME,
  UPDATE_ARTIFACT_TOOL_NAME,
])

export const artifactToolPresenter: ToolRowPresenter = {
  key: "artifact-tools",
  matches: artifactToolRowMatches,
  render: ({ activity, defaultOpen }) => (
    <ArtifactToolRow activity={activity} defaultOpen={defaultOpen} />
  ),
}

function artifactToolRowMatches(activity: ToolActivity) {
  if (ARTIFACT_TOOL_NAMES.has(activity.name) && activity.status !== "completed") {
    return true
  }
  if (
    activity.name === LIST_ARTIFACTS_TOOL_NAME &&
    artifactListToolResult(activity.result) !== null
  ) {
    return true
  }
  if (
    activity.name === READ_ARTIFACT_TOOL_NAME &&
    artifactReadToolResult(activity.result) !== null
  ) {
    return true
  }
  return (
    (activity.name === CREATE_ARTIFACT_TOOL_NAME || activity.name === UPDATE_ARTIFACT_TOOL_NAME) &&
    artifactToolResult(activity.result) !== null
  )
}
