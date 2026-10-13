// apps/web/src/features/conversations/components/video-understanding-presenter.tsx

import {
  AskVideoRow,
  FindVideoMomentsRow,
} from "@/features/conversations/components/video-understanding-row"
import {
  ASK_VIDEO_TOOL_NAME,
  askVideoResult,
  FIND_VIDEO_MOMENTS_TOOL_NAME,
  findVideoMomentsResult,
} from "@/features/conversations/native-tools/video-tools"
import type { ToolRowPresenter } from "@/integrations/contract"

// Running and failed calls keep the default row, which shows the progress stage.
export const videoUnderstandingPresenter: ToolRowPresenter = {
  key: "video-understanding",
  matches: (activity) =>
    activity.status === "completed" &&
    ((activity.name === FIND_VIDEO_MOMENTS_TOOL_NAME &&
      findVideoMomentsResult(activity.result) !== null) ||
      (activity.name === ASK_VIDEO_TOOL_NAME && askVideoResult(activity.result) !== null)),
  render: ({ activity, defaultOpen }) =>
    activity.name === ASK_VIDEO_TOOL_NAME ? (
      <AskVideoRow activity={activity} defaultOpen={defaultOpen} />
    ) : (
      <FindVideoMomentsRow activity={activity} defaultOpen={defaultOpen} />
    ),
}
