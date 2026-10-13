// apps/web/src/features/conversations/components/video-clips-presenter.tsx

import { CutVideoClipsRow } from "@/features/conversations/components/video-clips-row"
import {
  CUT_VIDEO_CLIPS_TOOL_NAME,
  cutVideoClipsResult,
} from "@/features/conversations/native-tools/video-tools"
import type { ToolRowPresenter } from "@/integrations/contract"

// Running and failed calls keep the default row, which shows the progress stage.
export const videoClipsPresenter: ToolRowPresenter = {
  key: "video-clips",
  matches: (activity) =>
    activity.status === "completed" &&
    activity.name === CUT_VIDEO_CLIPS_TOOL_NAME &&
    cutVideoClipsResult(activity.result) !== null,
  render: ({ activity, defaultOpen }) => (
    <CutVideoClipsRow activity={activity} defaultOpen={defaultOpen} />
  ),
}
