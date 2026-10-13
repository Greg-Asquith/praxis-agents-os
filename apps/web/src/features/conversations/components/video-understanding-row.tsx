// apps/web/src/features/conversations/components/video-understanding-row.tsx

import { useState, type ReactNode } from "react"
import { FilmIcon } from "lucide-react"

import { MarkdownContent } from "@/components/markdown/markdown-content"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { nodeText } from "@/components/tool-ui/untrusted-node"
import { Badge } from "@/components/ui/badge"
import { ActivityStatusBadge } from "@/features/conversations/components/tool-activity-status"
import { VideoFileCard } from "@/features/conversations/components/video-file-card"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  askVideoResult,
  findVideoMomentsResult,
  type VideoMoment,
} from "@/features/conversations/native-tools/video-tools"
import { formatDuration, pluralize } from "@/lib/format"
import { isRecord } from "@/lib/guards"
import { cn } from "@/lib/utils"

type RowProps = { activity: ToolActivity; defaultOpen: boolean }

export function FindVideoMomentsRow({ activity, defaultOpen }: RowProps) {
  const [selected, setSelected] = useState(0)
  const result = findVideoMomentsResult(activity.result)
  if (!result) {
    return null
  }
  const name = result.video.name ?? "Video"
  const count = result.moments.length
  const moment = result.moments[selected]
  return (
    <ToolResultCard
      ariaLabel={`Moments found in ${name}`}
      defaultOpen={defaultOpen}
      details={[
        { label: "Video", value: name },
        { label: "Moments", value: `${String(count)} ${pluralize(count, "Moment")}` },
      ]}
      heading={<VideoHeading>Find Video Moments</VideoHeading>}
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      <div className="grid min-w-0 gap-3">
        <VideoFileCard
          video={result.video}
          {...(moment ? { range: { startMs: moment.startMs, endMs: moment.endMs } } : {})}
        />
        {result.note ? <p className="text-muted-foreground text-xs">{result.note}</p> : null}
        {count > 0 ? (
          <ol aria-label="Moments" className="grid min-w-0 gap-2">
            {result.moments.map((item, index) => (
              <li className="min-w-0" key={`${String(item.startMs)}-${String(item.endMs)}`}>
                <MomentButton
                  moment={item}
                  onSelect={() => {
                    setSelected(index)
                  }}
                  selected={index === selected}
                />
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-muted-foreground text-sm">No moments fit the brief.</p>
        )}
      </div>
    </ToolResultCard>
  )
}

function MomentButton({
  moment,
  onSelect,
  selected,
}: {
  moment: VideoMoment
  onSelect: () => void
  selected: boolean
}) {
  const length = formatDuration(moment.endMs - moment.startMs, "milliseconds")
  const shots = `${String(moment.shotCount)} ${pluralize(moment.shotCount, "Shot")}`
  return (
    <button
      aria-pressed={selected}
      className={cn(
        "hover:bg-muted/40 grid w-full min-w-0 gap-1 rounded-md border p-3 text-left",
        selected && "border-primary bg-muted/40"
      )}
      onClick={onSelect}
      type="button"
    >
      <span className="flex min-w-0 items-start justify-between gap-2">
        <span className="min-w-0 text-sm font-medium wrap-break-word">{moment.title}</span>
        <Badge className="shrink-0" variant="outline">
          {`${String(moment.score)}/100`}
        </Badge>
      </span>
      <span className="text-muted-foreground text-xs tabular-nums">
        {`${moment.start}–${moment.end} · ${length} · ${shots}`}
      </span>
      {moment.hook ? <span className="text-xs wrap-break-word">“{moment.hook}”</span> : null}
      {moment.reason ? (
        <span className="text-muted-foreground text-xs wrap-break-word">{moment.reason}</span>
      ) : null}
    </button>
  )
}

export function AskVideoRow({ activity, defaultOpen }: RowProps) {
  const result = askVideoResult(activity.result)
  if (!result) {
    return null
  }
  const name = result.video.name ?? "Video"
  const question = isRecord(activity.args) ? nodeText(activity.args["question"]) : null
  return (
    <ToolResultCard
      ariaLabel={`Answer about ${name}`}
      defaultOpen={defaultOpen}
      details={[
        { label: "Video", value: name },
        { label: "Watched", value: `${result.start}–${result.end}` },
      ]}
      heading={<VideoHeading>Ask Video</VideoHeading>}
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      <div className="grid min-w-0 gap-3">
        <VideoFileCard video={result.video} {...(result.range ? { range: result.range } : {})} />
        {question ? (
          <div className="grid min-w-0 gap-1">
            <p className="text-muted-foreground text-xs font-medium">Question</p>
            <p className="text-sm wrap-break-word">{question}</p>
          </div>
        ) : null}
        <div className="grid min-w-0 gap-1">
          <p className="text-muted-foreground text-xs font-medium">Answer</p>
          <div className="border-input bg-muted/40 min-w-0 rounded-md border px-3 py-2.5">
            <MarkdownContent content={result.answer} />
          </div>
        </div>
      </div>
    </ToolResultCard>
  )
}

function VideoHeading({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <FilmIcon className="text-muted-foreground size-4 shrink-0" />
      <span>{children}</span>
    </span>
  )
}
