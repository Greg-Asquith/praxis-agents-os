// apps/web/src/features/conversations/components/video-tool-presenter.tsx

import type { ComponentType } from "react"

import { CutVideoClipsApproval } from "@/features/conversations/components/video-clips-approval"
import { CutVideoClipsRow } from "@/features/conversations/components/video-clips-row"
import {
  GenerateVideoLoadingRow,
  GenerateVideoRow,
} from "@/features/conversations/components/video-generation-row"
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
  GENERATE_VIDEO_TOOL_NAME,
  generateVideoResult,
  videoFileReferences,
} from "@/features/conversations/native-tools/video-tools"
import type { ToolRowPresenter } from "@/integrations/contract"

// Running and failed calls keep the default row, which shows the progress stage, unless
// a tool registers its own running card.
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

// The tool is automatic by default; an owner can set it to ask first.
const cutVideoClipsApproval: ToolRowPresenter = {
  handlesApprovals: true,
  key: "cut-video-clips-approval",
  matches: (activity) =>
    activity.status === "awaiting_approval" && activity.name === CUT_VIDEO_CLIPS_TOOL_NAME,
  render: ({ activity, approvalDecision, label, ui }) =>
    approvalDecision ? (
      <CutVideoClipsApproval
        activity={activity}
        controls={approvalDecision}
        label={label ?? activity.name}
        ui={ui ?? null}
      />
    ) : null,
}

const generateVideoRunning: ToolRowPresenter = {
  key: "generate-video-running",
  matches: (activity) =>
    activity.status === "running" && activity.name === GENERATE_VIDEO_TOOL_NAME,
  render: ({ activity, live }) => <GenerateVideoLoadingRow activity={activity} live={live} />,
}

export const videoToolPresenters: ToolRowPresenter[] = [
  cutVideoClipsApproval,
  generateVideoRunning,
  completedVideoTool(FIND_VIDEO_MOMENTS_TOOL_NAME, findVideoMomentsResult, FindVideoMomentsRow),
  completedVideoTool(ASK_VIDEO_TOOL_NAME, askVideoResult, AskVideoRow),
  completedVideoTool(CUT_VIDEO_CLIPS_TOOL_NAME, cutVideoClipsResult, CutVideoClipsRow),
  completedVideoTool(GENERATE_VIDEO_TOOL_NAME, generateVideoResult, GenerateVideoRow),
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
