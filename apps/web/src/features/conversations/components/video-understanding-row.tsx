// apps/web/src/features/conversations/components/video-understanding-row.tsx

import { use, useState } from "react"
import { FilmIcon, ScissorsIcon } from "lucide-react"

import { MarkdownContent } from "@/components/markdown/markdown-content"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { ToolHeading } from "@/components/tool-ui/tool-heading"
import { nodeText } from "@/components/tool-ui/untrusted-node"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { ConversationActionsContext } from "@/features/conversations/conversation-actions-context"
import { ActivityStatusBadge } from "@/features/conversations/components/tool-activity-status"
import { VideoFileCard } from "@/features/conversations/components/video-file-card"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  askVideoResult,
  cutMomentsInstruction,
  findVideoMomentsResult,
  type VideoMoment,
} from "@/features/conversations/native-tools/video-tools"
import { getErrorMessage } from "@/lib/api/errors"
import { formatDuration, pluralize } from "@/lib/format"
import { isRecord } from "@/lib/guards"
import { cn } from "@/lib/utils"

type RowProps = { activity: ToolActivity; defaultOpen: boolean }

export function FindVideoMomentsRow({ activity, defaultOpen }: RowProps) {
  const [selected, setSelected] = useState(0)
  // Moments left out of the cut, by index; all are in by default.
  const [excluded, setExcluded] = useState<ReadonlySet<number>>(() => new Set())
  const result = findVideoMomentsResult(activity.result)
  if (!result) {
    return null
  }
  const name = result.video.name ?? "Video"
  const count = result.moments.length
  const moment = result.moments[selected]
  const chosen = result.moments.filter((_, index) => !excluded.has(index))
  return (
    <ToolResultCard
      ariaLabel={`Moments found in ${name}`}
      defaultOpen={defaultOpen}
      details={[
        { label: "Video", value: name },
        { label: "Moments", value: `${String(count)} ${pluralize(count, "Moment")}` },
      ]}
      heading={<ToolHeading icon={FilmIcon}>Find Video Moments</ToolHeading>}
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      <div className="grid min-w-0 gap-3">
        <VideoFileCard range={moment ?? null} video={result.video} />
        {result.note ? <p className="text-muted-foreground text-xs">{result.note}</p> : null}
        {count > 0 ? (
          <ol aria-label="Moments" className="grid min-w-0 gap-2">
            {result.moments.map((item, index) => (
              <li
                className="flex min-w-0 items-start gap-3"
                key={`${String(item.startMs)}-${String(item.endMs)}`}
              >
                <Checkbox
                  aria-label={`Include Moment ${String(index + 1)}`}
                  checked={!excluded.has(index)}
                  className="mt-3.5"
                  onCheckedChange={(checked) => {
                    setExcluded((current) => {
                      const next = new Set(current)
                      if (checked) {
                        next.delete(index)
                      } else {
                        next.add(index)
                      }
                      return next
                    })
                  }}
                />
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
        {count > 0 ? <CutMomentsAction moments={chosen} videoName={name} /> : null}
      </div>
    </ToolResultCard>
  )
}

function CutMomentsAction({ moments, videoName }: { moments: VideoMoment[]; videoName: string }) {
  const sendInstruction = use(ConversationActionsContext)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const count = moments.length

  async function handleCut() {
    if (!sendInstruction) {
      return
    }
    setError(null)
    setSending(true)
    try {
      await sendInstruction(cutMomentsInstruction(videoName, moments))
    } catch (sendError) {
      setError(getErrorMessage(sendError))
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
      {error ? <p className="text-destructive mr-auto text-xs">{error}</p> : null}
      <Button
        disabled={!sendInstruction || sending || count === 0}
        onClick={() => {
          void handleCut()
        }}
        size="sm"
        type="button"
      >
        <ScissorsIcon />
        {count === 0 ? "Cut Clips" : `Cut ${String(count)} ${pluralize(count, "Clip")}`}
      </Button>
    </div>
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
      heading={<ToolHeading icon={FilmIcon}>Ask Video</ToolHeading>}
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      <div className="grid min-w-0 gap-3">
        <VideoFileCard range={result.range} video={result.video} />
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
