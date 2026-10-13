// apps/web/src/features/conversations/components/video-tool-presenter.tsx

import { VideoToolRow } from "@/features/conversations/components/video-tool-row"
import { videoFileReferences } from "@/features/conversations/native-tools/video-tools"
import type { ToolRowPresenter } from "@/integrations/contract"

// Any completed result that names a video File, unless a more specific presenter claims it.
export const videoResultPresenter: ToolRowPresenter = {
  key: "video-result",
  matches: (activity) =>
    activity.status === "completed" && videoFileReferences(activity.result) !== null,
  render: ({ activity, label }) => (
    <VideoToolRow activity={activity} label={label ?? activity.name} />
  ),
}
