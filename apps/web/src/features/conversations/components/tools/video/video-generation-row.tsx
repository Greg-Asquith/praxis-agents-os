// apps/web/src/features/conversations/components/tools/video/video-generation-row.tsx

import { ClapperboardIcon, WandSparklesIcon } from "lucide-react"

import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"

import { ToolResultCard } from "@/components/tool-ui/result-card"
import { ToolHeading } from "@/components/tool-ui/tool-heading"
import { nodeText } from "@/components/tool-ui/untrusted-node"
import { AiGeneratedBadge } from "@/features/files/components/file-status-badge"
import { MediaInputPreview } from "@/features/conversations/components/tools/files/media-input-preview"
import { ActivityStatusBadge } from "@/features/conversations/components/tool-rows/tool-activity-status"
import { VideoFileCard } from "@/features/conversations/components/tools/video/video-file-card"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  editVideoResult,
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
  const prompt = argText(activity, "prompt")
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
        <ArgText label="Prompt" text={prompt} />
        <References activity={activity} />
      </div>
    </ToolResultCard>
  )
}

export function EditVideoRow({
  activity,
  defaultOpen,
}: {
  activity: ToolActivity
  defaultOpen: boolean
}) {
  const result = editVideoResult(activity.result)
  if (!result) {
    return null
  }
  return (
    <ToolResultCard
      ariaLabel={`Edited ${result.video.name ?? "video"}`}
      defaultOpen={defaultOpen}
      details={[
        { label: "Saved As", value: `Version ${String(result.revisionNumber)}` },
        ...(result.costUsd ? [{ label: "Cost", value: `$${result.costUsd}` }] : []),
      ]}
      heading={<ToolHeading icon={WandSparklesIcon}>Edit Video</ToolHeading>}
      trailing={
        <>
          <AiGeneratedBadge />
          <ActivityStatusBadge status={activity.status} />
        </>
      }
    >
      <div className="grid min-w-0 gap-3">
        <VideoFileCard video={result.video} />
        <ArgText label="Instruction" text={argText(activity, "instruction")} />
      </div>
    </ToolResultCard>
  )
}

// The images and clips the generation drew on, when the agent passed any.
function References({ activity }: { activity: ToolActivity }) {
  const args = isRecord(activity.args) ? activity.args : {}
  const has = (key: string) => Array.isArray(args[key]) && args[key].length > 0
  if (!has("image_file_ids") && !has("reference_video_file_ids")) {
    return null
  }
  return (
    <div className="grid min-w-0 gap-1">
      <p className="text-muted-foreground text-xs font-medium">References</p>
      <MediaInputPreview args={args} field="image_file_ids" kind="image" />
      <MediaInputPreview args={args} field="reference_video_file_ids" kind="video" />
    </div>
  )
}

function argText(activity: ToolActivity, key: string): string | null {
  return isRecord(activity.args) ? nodeText(activity.args[key]) : null
}

function ArgText({ label, text }: { label: string; text: string | null }) {
  if (!text) {
    return null
  }
  return (
    <div className="grid min-w-0 gap-1">
      <p className="text-muted-foreground text-xs font-medium">{label}</p>
      <p className="text-sm wrap-break-word">{text}</p>
    </div>
  )
}

// An edit takes as long as a generation, so its running card says so too.
export function EditVideoLoadingRow({ activity }: { activity: ToolActivity }) {
  return (
    <FanOutSkeleton
      heading={<ToolHeading icon={WandSparklesIcon}>Edit Video</ToolHeading>}
      label="Editing a video"
      summary={`${activity.progressStage ?? "Editing Video"} · Usually takes 1 to 3 minutes`}
      running
    />
  )
}

// A clip takes one to several minutes, so the running card says what's coming and how long.
export function GenerateVideoLoadingRow({ activity }: { activity: ToolActivity }) {
  const stage = activity.progressStage ?? "Generating Video"
  return (
    <FanOutSkeleton
      heading={<ToolHeading icon={ClapperboardIcon}>Generate Video</ToolHeading>}
      label="Generating a video"
      summary={`${stage} · ${generateVideoPlan(activity.args)} · Usually takes 1 to 3 minutes`}
      running
    />
  )
}
