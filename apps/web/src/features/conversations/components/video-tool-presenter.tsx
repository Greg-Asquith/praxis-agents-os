// apps/web/src/features/conversations/components/video-tool-presenter.tsx

import type { ComponentType } from "react"

import { CutVideoClipsRow } from "@/features/conversations/components/video-clips-row"
import { VideoToolRow } from "@/features/conversations/components/video-tool-row"
import {
  AskVideoRow,
  FindVideoMomentsRow,
} from "@/features/conversations/components/video-understanding-row"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  ASK_VIDEO_TOOL_NAME,
  askVideoResult,
  CUT_VIDEO_CLIPS_TOOL_NAME,
  cutVideoClipsResult,
  FIND_VIDEO_MOMENTS_TOOL_NAME,
  findVideoMomentsResult,
  videoFileReferences,
} from "@/features/conversations/native-tools/video-tools"
import type { ToolRowPresenter } from "@/integrations/contract"

// Running and failed calls keep the default row, which shows the progress stage.
function completedVideoTool(
  name: string,
  parse: (value: unknown) => unknown,
  Row: ComponentType<{ activity: ToolActivity; defaultOpen: boolean }>
): ToolRowPresenter {
  return {
    key: name,
    matches: (activity) =>
      activity.status === "completed" && activity.name === name && parse(activity.result) !== null,
    render: ({ activity, defaultOpen }) => <Row activity={activity} defaultOpen={defaultOpen} />,
  }
}

export const videoToolPresenters: ToolRowPresenter[] = [
  completedVideoTool(FIND_VIDEO_MOMENTS_TOOL_NAME, findVideoMomentsResult, FindVideoMomentsRow),
  completedVideoTool(ASK_VIDEO_TOOL_NAME, askVideoResult, AskVideoRow),
  completedVideoTool(CUT_VIDEO_CLIPS_TOOL_NAME, cutVideoClipsResult, CutVideoClipsRow),
]

// Any completed result that names a video File, unless a more specific presenter claims it.
export const videoResultPresenter: ToolRowPresenter = {
  key: "video-result",
  matches: (activity) =>
    activity.status === "completed" && videoFileReferences(activity.result) !== null,
  render: ({ activity, label }) => (
    <VideoToolRow activity={activity} label={label ?? activity.name} />
  ),
}
