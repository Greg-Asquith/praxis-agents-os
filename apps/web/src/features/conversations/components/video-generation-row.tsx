// apps/web/src/features/conversations/components/video-generation-row.tsx

import { ClapperboardIcon } from "lucide-react"

import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"

import { ToolResultCard } from "@/components/tool-ui/result-card"
import { ToolHeading } from "@/components/tool-ui/tool-heading"
import { nodeText } from "@/components/tool-ui/untrusted-node"
import { AiGeneratedBadge } from "@/features/files/components/file-status-badge"
import {
  ActivityStatusBadge,
  ActivityStatusSuffix,
} from "@/features/conversations/components/tool-activity-status"
import { VideoFileCard } from "@/features/conversations/components/video-file-card"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  generateVideoPlan,
  generateVideoResult,
} from "@/features/conversations/native-tools/video-tools"
import { isRecord } from "@/lib/guards"

const SHAPES: Record<string, string> = { "9:16": "Vertical (9:16)", "16:9": "Landscape (16:9)" }

export function GenerateVideoRow({
  activity,
  defaultOpen,
}: {
  activity: ToolActivity
  defaultOpen: boolean
}) {
  const result = generateVideoResult(activity.result)
  if (!result) {
    return null
  }
  const prompt = isRecord(activity.args) ? nodeText(activity.args["prompt"]) : null
  return (
    <ToolResultCard
      ariaLabel={`Generated ${result.video.name ?? "video"}`}
      defaultOpen={defaultOpen}
      details={[
        { label: "Shape", value: SHAPES[result.aspectRatio] ?? result.aspectRatio },
        { label: "Length", value: `${String(result.durationSeconds)} s` },
        { label: "Resolution", value: result.resolution === "4k" ? "4K" : result.resolution },
        ...(result.costUsd ? [{ label: "Cost", value: `$${result.costUsd}` }] : []),
      ]}
      heading={<ToolHeading icon={ClapperboardIcon}>Generate Video</ToolHeading>}
      trailing={
        <>
          <AiGeneratedBadge />
          <ActivityStatusBadge status={activity.status} />
        </>
      }
    >
      <div className="grid min-w-0 gap-3">
        <VideoFileCard video={result.video} />
        {prompt ? (
          <div className="grid min-w-0 gap-1">
            <p className="text-muted-foreground text-xs font-medium">Prompt</p>
            <p className="text-sm wrap-break-word">{prompt}</p>
          </div>
        ) : null}
      </div>
    </ToolResultCard>
  )
}

// A clip takes one to several minutes, so the running card says what's coming and how long.
export function GenerateVideoLoadingRow({
  activity,
  live,
}: {
  activity: ToolActivity
  live: boolean
}) {
  const stage = activity.progressStage ?? "Generating Video"
  return (
    <FanOutSkeleton
      heading={<ToolHeading icon={ClapperboardIcon}>Generate Video</ToolHeading>}
      label="Generating a video"
      summary={`${stage} · ${generateVideoPlan(activity.args)} · Usually takes 1 to 3 minutes`}
      {...(live
        ? { trailing: <ActivityStatusSuffix liveRunning status="running" suffix={null} /> }
        : {})}
    />
  )
}
