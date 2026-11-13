// apps/web/src/integrations/google_ads/components/upload-media-approval.tsx

import { PencilIcon, PlusIcon, XIcon } from "lucide-react"
import { useMemo, useState } from "react"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-types"
import type { EditedValue } from "@/components/tool-ui/edited-values"
import { WorkspaceFileThumbnail } from "@/components/tool-ui/workspace-file-thumbnail"
import { Button } from "@/components/ui/button"
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover"
import { Textarea } from "@/components/ui/textarea"
import {
  DataTable,
  type DataColumn,
  type DataRow,
  type DataTableTab,
} from "@/components/ui/data-table"
import { AttentionLine } from "@/integrations/ads/components/attention-line"
import { CancelCell } from "@/integrations/ads/components/cancel-cell"
import { ChangeSummary } from "@/integrations/ads/components/change-summary"
import { CommittedInput } from "@/integrations/ads/components/committed-input"
import { FormField } from "@/integrations/ads/components/controls"
import { EntitySearch } from "@/integrations/ads/components/entity-search"
import { CheckChanges } from "@/integrations/google_ads/components/check-changes"
import {
  editFiles,
  editVideoText,
  keptVideoText,
  fileSize,
  fitsText,
  MAX_DESCRIPTION,
  MAX_FILES,
  MAX_TITLE,
  MAX_UPLOADS,
  MAX_VIDEOS,
  serializeCancelled,
  uploadCounts,
  videoTextFor,
  videoTextProblem,
  youtubeVideoId,
  type FileRow,
  type ImageFieldType,
  type UploadMediaArgs,
  type VideoText,
} from "@/integrations/google_ads/lib/upload-media"
import { formatDuration } from "@/lib/format"
import { cn } from "@/lib/utils"

// Below this many Files the selection and search only add noise.
const TOOLS_FROM = 10

/** Only the columns the Files need: a title for videos, fits for images. */
function columns(hasImages: boolean, hasVideos: boolean): DataColumn[] {
  const details = hasImages ? (hasVideos ? "Dimensions or Length" : "Dimensions") : "Length"
  return [
    { key: "name", kind: "text", label: "Name", width: 260 },
    ...(hasVideos
      ? [{ key: "title", kind: "text", label: "YouTube Title", width: 240 } as const]
      : []),
    { key: "size", kind: "text", label: "Size", width: 100 },
    { key: "details", kind: "text", label: details, width: hasVideos && hasImages ? 180 : 120 },
    ...(hasImages ? [{ key: "fits", kind: "text", label: "Fits", width: 200 } as const] : []),
    { key: "cancel", kind: "text", label: "Cancel", width: 90 },
  ]
}

const SHAPE_TABS: { id: string; label: string; types: ImageFieldType[] }[] = [
  { id: "landscape", label: "Landscape", types: ["MARKETING_IMAGE"] },
  { id: "square", label: "Square", types: ["SQUARE_MARKETING_IMAGE"] },
  { id: "portrait", label: "Portrait", types: ["PORTRAIT_MARKETING_IMAGE"] },
  { id: "logo", label: "Logo", types: ["LOGO", "LANDSCAPE_LOGO"] },
]

export function UploadMediaApproval({
  args,
  controls,
  disabled,
  onFieldEdit,
}: {
  args: UploadMediaArgs
  controls: ToolApprovalDecisionControls
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const [tab, setTab] = useState("all")
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set())
  const [adding, setAdding] = useState(false)
  const counts = uploadCounts(args)
  const byId = useMemo(() => new Map(args.files.map((file) => [file.id, file])), [args.files])
  const tools = args.files.length >= TOOLS_FROM
  const tabs = useMemo(() => fileTabs(byId), [byId])
  const tableRows = useMemo<DataRow[]>(
    () =>
      args.files.map((file) => ({
        cancel: "",
        details: fileDetails(file),
        fits: fileFits(file),
        key: file.id,
        name: file.check?.name ?? file.label,
        size: file.check ? fileSize(file.check.kind, file.check.sizeBytes) : "—",
        title: file.check?.kind === "video" ? videoTextFor(args, file).title : "—",
      })),
    [args]
  )

  const edit = (ids: Iterable<string>, cancelled: boolean) => {
    const next = editFiles(args.files, new Set(ids), cancelled)
    controls.onRetain?.(serializeCancelled(next.rows))
    // Empty lists go as null, since every field is optional.
    onFieldEdit("files", next.files.length > 0 ? next.files : null)
    // A cancelled video's title would name a File the request no longer has.
    if (args.videoText.size > 0) {
      const details = keptVideoText(args, next.rows)
      onFieldEdit("video_details", details.length > 0 ? details : null)
    }
  }
  const editVideos = (videos: string[]) => {
    onFieldEdit("youtube_videos", videos.length > 0 ? videos : null)
  }
  const editText = (fileId: string, change: Partial<VideoText>) => {
    onFieldEdit("video_details", editVideoText(args, fileId, change))
  }
  const problemIds = args.files
    .filter((file) => !file.cancelled && file.check?.problem)
    .map((file) => file.id)

  return (
    <div className="grid min-w-0 gap-3">
      <ChangeSummary
        lines={[
          {
            count: counts.images,
            detail: "from workspace Files",
            id: "images",
            label: "Upload Images",
          },
          {
            count: counts.videoFiles,
            detail: "to an unlisted YouTube channel Google manages for this account",
            id: "video-files",
            label: "Upload Videos",
          },
          {
            count: counts.links,
            detail: "by their links",
            id: "videos",
            label: "Link YouTube Videos",
          },
          {
            count: counts.uploads,
            detail: "that were still processing",
            id: "uploads",
            label: "Finish Earlier Uploads",
          },
          {
            count: counts.problems,
            detail: "too large or a format Google doesn't take",
            id: "attention",
            label: "Needs Attention",
            tone: "danger",
            onSelect: () => {
              setTab("attention")
            },
            selected: tab === "attention",
            action: (
              <Button
                disabled={disabled}
                onClick={() => {
                  edit(problemIds, true)
                }}
                size="sm"
                type="button"
                variant="outline"
              >
                Cancel These {String(counts.problems)}
              </Button>
            ),
          },
        ]}
      />
      <AttentionLine
        count={counts.problems}
        onShow={() => {
          setTab("attention")
        }}
      />
      {args.files.length > 0 ? (
        <DataTable
          activeTab={tab}
          columns={columns(
            args.files.some((file) => file.check?.kind !== "video"),
            args.files.some((file) => file.check?.kind === "video")
          )}
          exportFilename="google-ads-media-upload.csv"
          onTabChange={setTab}
          pageSize={25}
          renderCell={(column, row) => {
            const file = byId.get(String(row["key"]))
            if (!file) return null
            if (column.key === "name") return <NameCell file={file} />
            if (column.key === "title" && file.check?.kind === "video" && !file.cancelled)
              return (
                <TitleCell
                  disabled={disabled}
                  name={file.check.name}
                  onText={(change) => {
                    editText(file.id, change)
                  }}
                  text={videoTextFor(args, file)}
                />
              )
            if (column.key === "cancel")
              return (
                <CancelCell
                  cancelled={file.cancelled}
                  disabled={disabled}
                  onCancel={() => {
                    edit([file.id], true)
                  }}
                  onUndo={() => {
                    edit([file.id], false)
                  }}
                />
              )
            return null
          }}
          rowClassName={(row) =>
            byId.get(String(row["key"]))?.cancelled ? "opacity-60" : undefined
          }
          rowDetails={false}
          rowNoun={["File", "Files"]}
          rows={tableRows}
          tabs={tabs}
          {...(tools
            ? {
                searchable: true,
                selection: {
                  actions: (
                    <Button
                      disabled={disabled}
                      onClick={() => {
                        edit(selected, true)
                        setSelected(new Set())
                      }}
                      size="sm"
                      type="button"
                      variant="outline"
                    >
                      Cancel These Changes
                    </Button>
                  ),
                  onChange: setSelected,
                  rowId: (row) => String(row["key"]),
                  selected,
                },
              }
            : {})}
        />
      ) : null}
      {counts.videoFiles > 0 ? (
        <p className="text-muted-foreground text-sm">
          Videos go to an unlisted YouTube channel that Google manages for this account. Their
          titles and descriptions can&apos;t change after the upload.
        </p>
      ) : null}
      {adding ? (
        <EntitySearch
          fieldKey="files"
          isTaken={(choice) => byId.has(String(choice.value["entity_id"]))}
          label="Search Files"
          onChoose={(choice) => {
            const files = args.files.filter((file) => !file.cancelled).map((file) => file.raw)
            onFieldEdit("files", [...files, choice.value])
            setAdding(false)
          }}
          toolName="google_ads_upload_media"
        />
      ) : null}
      {args.needsReview ? (
        <CheckChanges
          canCheck
          disabled={disabled}
          label="Check Files"
          note="You changed the Files, so they need checking again."
          onCheck={controls.onReview}
          submitting={controls.submitting}
        />
      ) : null}
      <VideoFields disabled={disabled} onChange={editVideos} videos={args.videos} />
      <EarlierUploads
        disabled={disabled}
        onChange={(uploads) => {
          onFieldEdit("video_uploads", uploads.length > 0 ? uploads : null)
        }}
        uploads={args.uploads}
      />
      <div className="flex flex-wrap items-center gap-3">
        <Button
          disabled={disabled || (!adding && counts.images + counts.videoFiles >= MAX_FILES)}
          onClick={() => {
            setAdding(!adding)
          }}
          type="button"
          variant="outline"
        >
          <PlusIcon />
          {adding ? "Cancel" : "Add Files"}
        </Button>
        <Button
          disabled={disabled || args.videos.length >= MAX_VIDEOS}
          onClick={() => {
            editVideos([...args.videos, ""])
          }}
          type="button"
          variant="outline"
        >
          <PlusIcon />
          Add YouTube Video
        </Button>
        <p className="text-muted-foreground text-sm">
          Approval uses these versions. If a File changes before the upload runs, it stops.
        </p>
      </div>
    </div>
  )
}

function fileDetails(file: FileRow): string {
  const check = file.check
  if (check?.kind === "video")
    return check.durationMs === null ? "—" : formatDuration(check.durationMs, "milliseconds")
  return check?.width && check.height ? `${String(check.width)} × ${String(check.height)}` : "—"
}

function fileFits(file: FileRow): string {
  if (!file.check || file.check.problem) return "—"
  if (file.check.kind === "video") return "Video"
  return fitsText(file.check.fits, file.check.tooSmall)
}

function fileTabs(byId: ReadonlyMap<string, FileRow>): DataTableTab[] {
  const live = (row: DataRow, match: (file: FileRow) => boolean) => {
    const file = byId.get(String(row["key"]))
    return file !== undefined && !file.cancelled && match(file)
  }
  return [
    { id: "all", label: "All", match: () => true },
    ...SHAPE_TABS.map((shape) => ({
      id: shape.id,
      label: shape.label,
      hideWhenEmpty: true,
      match: (row: DataRow) =>
        live(row, (file) => file.check?.fits.some((type) => shape.types.includes(type)) ?? false),
    })),
    {
      id: "videos",
      label: "Videos",
      hideWhenEmpty: true,
      match: (row) => live(row, (file) => file.check?.kind === "video"),
    },
    {
      id: "attention",
      label: "Needs Attention",
      hideWhenEmpty: true,
      match: (row) => live(row, (file) => Boolean(file.check?.problem)),
    },
  ]
}

function NameCell({ file }: { file: FileRow }) {
  const name = file.check?.name ?? file.label
  return (
    <span className="flex min-w-0 items-center gap-2.5">
      <WorkspaceFileThumbnail
        className="size-8"
        fileId={file.id}
        kind={file.check?.kind ?? "image"}
        label={name}
        revisionId={file.check?.revisionId ?? null}
      />
      <span className="grid min-w-0 gap-0.5 text-sm">
        <span className="truncate">{name}</span>
        {!file.cancelled && file.check?.problem ? (
          <span className="text-destructive text-xs wrap-anywhere whitespace-normal">
            {file.check.problem}
          </span>
        ) : null}
        {!file.cancelled && !file.check ? (
          <span className="text-muted-foreground text-xs">Not checked yet.</span>
        ) : null}
      </span>
    </span>
  )
}

/** A video's title on one line; its title and description are edited in a popover. */
function TitleCell({
  disabled,
  name,
  onText,
  text,
}: {
  disabled: boolean
  name: string
  onText: (change: Partial<VideoText>) => void
  text: VideoText
}) {
  const problem = videoTextProblem(text)
  return (
    <span className="grid min-w-0 gap-0.5">
      <Popover>
        <PopoverTrigger
          render={
            <Button
              aria-label={`Edit YouTube title for ${name}`}
              className="h-7 min-w-0 justify-between gap-2 px-2 font-normal"
              disabled={disabled}
              size="sm"
              type="button"
              variant="ghost"
            />
          }
        >
          <span className="truncate">{text.title || "Add a title"}</span>
          <PencilIcon className="text-muted-foreground shrink-0" />
        </PopoverTrigger>
        <PopoverContent align="start" className="w-[min(28rem,calc(100vw-2rem))] gap-3">
          <PopoverHeader>
            <PopoverTitle>YouTube Details</PopoverTitle>
            <PopoverDescription className="wrap-anywhere">{name}</PopoverDescription>
          </PopoverHeader>
          <VideoTextFields disabled={disabled} name={name} onText={onText} text={text} />
        </PopoverContent>
      </Popover>
      {problem ? <span className="text-destructive px-2 text-xs">{problem}</span> : null}
    </span>
  )
}

function VideoTextFields({
  disabled,
  name,
  onText,
  text,
}: {
  disabled: boolean
  name: string
  onText: (change: Partial<VideoText>) => void
  text: VideoText
}) {
  const count = text.title.length
  return (
    <div className="grid gap-3">
      <FormField label="Title">
        {(id) => (
          <span className="flex items-center gap-2">
            <CommittedInput
              ariaLabel={`YouTube title for ${name}`}
              className="text-sm"
              disabled={disabled}
              id={id}
              onCommit={(title) => {
                onText({ title })
              }}
              value={text.title}
            />
            <span
              className={cn(
                "w-14 shrink-0 text-right text-xs tabular-nums",
                count > MAX_TITLE ? "text-destructive font-medium" : "text-muted-foreground"
              )}
            >
              {String(count)}/{String(MAX_TITLE)}
            </span>
          </span>
        )}
      </FormField>
      <FormField label="Description">
        {(id) => (
          <Textarea
            key={text.description}
            aria-label={`YouTube description for ${name}`}
            className="text-sm"
            defaultValue={text.description}
            disabled={disabled}
            id={id}
            maxLength={MAX_DESCRIPTION}
            onBlur={(event) => {
              if (event.currentTarget.value !== text.description)
                onText({ description: event.currentTarget.value })
            }}
            placeholder="Optional"
            rows={3}
          />
        )}
      </FormField>
    </div>
  )
}

function EarlierUploads({
  disabled,
  onChange,
  uploads,
}: {
  disabled: boolean
  onChange: (uploads: string[]) => void
  uploads: readonly string[]
}) {
  if (uploads.length === 0) return null
  return (
    <section aria-label="Earlier video uploads" className="grid gap-2">
      <h4 className="text-sm font-medium">Finish Earlier Uploads</h4>
      <ul className="divide-y overflow-hidden rounded-lg border">
        {uploads.slice(0, MAX_UPLOADS).map((upload) => (
          <li key={upload} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
            <span className="wrap-anywhere">Upload {upload}</span>
            <Button
              aria-label={`Remove upload ${upload}`}
              disabled={disabled}
              onClick={() => {
                onChange(uploads.filter((other) => other !== upload))
              }}
              size="icon-xs"
              type="button"
              variant="ghost"
            >
              <XIcon />
            </Button>
          </li>
        ))}
      </ul>
      <p className="text-muted-foreground text-xs">
        These videos were still processing. Each becomes a video asset once Google has processed it.
      </p>
    </section>
  )
}

function VideoFields({
  disabled,
  onChange,
  videos,
}: {
  disabled: boolean
  onChange: (videos: string[]) => void
  videos: readonly string[]
}) {
  if (videos.length === 0) return null
  return (
    <section aria-label="YouTube videos" className="grid gap-2">
      <h4 className="text-sm font-medium">YouTube Videos</h4>
      {videos.map((video, index) => {
        const invalid = youtubeVideoId(video) === null
        return (
          // eslint-disable-next-line react-x/no-array-index-key -- A link has no ID until it's valid, and links can repeat.
          <div key={index} className="grid gap-1">
            <div className="flex items-center gap-2">
              <CommittedInput
                ariaLabel={`YouTube video ${String(index + 1)}`}
                className="h-8 text-sm"
                disabled={disabled}
                onCommit={(value) => {
                  onChange(videos.map((item, other) => (other === index ? value : item)))
                }}
                placeholder="https://www.youtube.com/watch?v=…"
                value={video}
              />
              <Button
                aria-label={`Remove YouTube video ${String(index + 1)}`}
                disabled={disabled}
                onClick={() => {
                  onChange(videos.filter((_item, other) => other !== index))
                }}
                size="icon-xs"
                type="button"
                variant="ghost"
              >
                <XIcon />
              </Button>
            </div>
            {invalid ? (
              <p className="text-destructive text-xs">
                Enter a YouTube link, such as youtube.com/watch?v=…, or an 11-character video ID.
              </p>
            ) : null}
          </div>
        )
      })}
      <p className="text-muted-foreground text-xs">
        Linked, not uploaded. The video stays on YouTube.
      </p>
    </section>
  )
}
