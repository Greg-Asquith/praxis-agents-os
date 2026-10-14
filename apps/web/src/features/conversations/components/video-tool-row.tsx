// apps/web/src/features/conversations/components/video-tool-row.tsx

import { VideoIcon } from "lucide-react"

import { ToolResultCard } from "@/components/tool-ui/result-card"
import { ToolHeading } from "@/components/tool-ui/tool-heading"
import { ActivityStatusBadge } from "@/features/conversations/components/tool-activity-status"
import { VideoFileCard } from "@/features/conversations/components/video-file-card"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { videoFileReferences } from "@/features/conversations/native-tools/video-tools"
import { pluralize } from "@/lib/format"

export function VideoToolRow({ activity, label }: { activity: ToolActivity; label: string }) {
  const videos = videoFileReferences(activity.result)
  if (!videos) {
    return null
  }
  const countLabel = `${String(videos.length)} ${pluralize(videos.length, "Video")}`
  return (
    <ToolResultCard
      ariaLabel={label}
      defaultOpen
      details={[{ label: "Videos", value: countLabel }]}
      heading={<ToolHeading icon={VideoIcon}>{label}</ToolHeading>}
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      <div className="grid min-w-0 gap-3" role="list">
        {videos.map((video) => (
          <div key={video.fileId} role="listitem">
            <VideoFileCard video={video} />
          </div>
        ))}
      </div>
    </ToolResultCard>
  )
}
