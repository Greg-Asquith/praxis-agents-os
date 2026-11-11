// apps/web/src/integrations/google_ads/components/upload-media-approval.tsx

import { PlusIcon, XIcon } from "lucide-react"
import { useMemo, useState } from "react"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-types"
import type { EditedValue } from "@/components/tool-ui/edited-values"
import { WorkspaceFileThumbnail } from "@/components/tool-ui/workspace-file-thumbnail"
import { Button } from "@/components/ui/button"
import {
  DataTable,
  type DataColumn,
  type DataRow,
  type DataTableTab,
} from "@/components/ui/data-table"
import { AttentionLine } from "@/integrations/ads/components/attention-line"
import { CancelCell } from "@/integrations/ads/components/cancel-cell"
import { ChangeSummary, type ChangeSummaryLine } from "@/integrations/ads/components/change-summary"
import { CommittedInput } from "@/integrations/ads/components/committed-input"
import { EntitySearch } from "@/integrations/ads/components/entity-search"
import { CheckChanges } from "@/integrations/google_ads/components/check-changes"
import {
  editImages,
  fitsText,
  kilobytes,
  serializeCancelled,
  uploadCounts,
  youtubeVideoId,
  type ImageFieldType,
  type ImageRow,
  type UploadMediaArgs,
} from "@/integrations/google_ads/lib/upload-media"

// Below this many images the selection and search only add noise.
const TOOLS_FROM = 10
const MAX_VIDEOS = 20

const COLUMNS: DataColumn[] = [
  { key: "name", kind: "text", label: "Name", width: 280 },
  { key: "size", kind: "text", label: "Size", width: 100 },
  { key: "dimensions", kind: "text", label: "Dimensions", width: 120 },
  { key: "fits", kind: "text", label: "Fits", width: 220 },
  { key: "cancel", kind: "text", label: "Cancel", width: 80 },
]

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
  const byId = useMemo(() => new Map(args.images.map((image) => [image.id, image])), [args.images])
  const tools = args.images.length >= TOOLS_FROM
  const tabs = useMemo(() => imageTabs(byId), [byId])
  const tableRows = useMemo<DataRow[]>(
    () =>
      args.images.map((image) => ({
        cancel: "",
        dimensions:
          image.check?.width && image.check.height
            ? `${String(image.check.width)} × ${String(image.check.height)}`
            : "—",
        fits:
          image.check && !image.check.problem
            ? fitsText(image.check.fits, image.check.tooSmall)
            : "—",
        key: image.id,
        name: image.check?.name ?? image.label,
        size: image.check ? kilobytes(image.check.sizeBytes) : "—",
      })),
    [args.images]
  )

  const edit = (ids: Iterable<string>, cancelled: boolean) => {
    const next = editImages(args.images, new Set(ids), cancelled)
    controls.onRetain?.(serializeCancelled(next.rows))
    onFieldEdit("files", next.files)
  }
  const editVideos = (videos: string[]) => {
    onFieldEdit("youtube_videos", videos)
  }
  const lineFor = (
    id: string,
    label: string,
    count: number,
    extra: Partial<ChangeSummaryLine> = {}
  ): ChangeSummaryLine => ({ count, id, label, ...extra })
  const problemIds = args.images
    .filter((image) => !image.cancelled && image.check?.problem)
    .map((image) => image.id)

  return (
    <div className="grid min-w-0 gap-3">
      <ChangeSummary
        lines={[
          lineFor("images", "Upload Images", counts.images - counts.problems, {
            detail: "from workspace Files",
          }),
          lineFor("videos", "Link YouTube Videos", counts.videos, { detail: "by their links" }),
          lineFor("attention", "Needs Attention", counts.problems, {
            detail: "too large or a format Google doesn't take",
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
          }),
        ]}
      />
      <AttentionLine
        count={counts.problems}
        onShow={() => {
          setTab("attention")
        }}
      />
      {args.images.length > 0 ? (
        <DataTable
          activeTab={tab}
          columns={COLUMNS}
          exportFilename="google-ads-media-upload.csv"
          onTabChange={setTab}
          pageSize={25}
          renderCell={(column, row) => {
            const image = byId.get(String(row["key"]))
            if (!image) return null
            if (column.key === "name") return <NameCell image={image} />
            if (column.key === "cancel")
              return (
                <CancelCell
                  cancelled={image.cancelled}
                  disabled={disabled}
                  onCancel={() => {
                    edit([image.id], true)
                  }}
                  onUndo={() => {
                    edit([image.id], false)
                  }}
                />
              )
            return null
          }}
          rowClassName={(row) =>
            byId.get(String(row["key"]))?.cancelled ? "opacity-60" : undefined
          }
          rowDetails={false}
          rowNoun={["image", "images"]}
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
      {adding ? (
        <EntitySearch
          fieldKey="files"
          isTaken={(choice) => byId.has(String(choice.value["entity_id"]))}
          label="Search Files"
          onChoose={(choice) => {
            const files = args.images.filter((image) => !image.cancelled).map((image) => image.raw)
            onFieldEdit("files", [...files, choice.value])
            setAdding(false)
          }}
          toolName="google_ads_upload_media"
        />
      ) : null}
      {args.needsReview && counts.images > 0 ? (
        <CheckChanges
          canCheck
          disabled={disabled}
          label="Check Files"
          note="You changed the images, so they need checking again."
          onCheck={controls.onReview}
          submitting={controls.submitting}
        />
      ) : null}
      <VideoFields disabled={disabled} onChange={editVideos} videos={args.videos} />
      <div className="flex flex-wrap items-center gap-3">
        <Button
          disabled={disabled}
          onClick={() => {
            setAdding(!adding)
          }}
          type="button"
          variant="outline"
        >
          <PlusIcon />
          {adding ? "Cancel" : "Add Images"}
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

function imageTabs(byId: ReadonlyMap<string, ImageRow>): DataTableTab[] {
  const live = (row: DataRow, match: (image: ImageRow) => boolean) => {
    const image = byId.get(String(row["key"]))
    return image !== undefined && !image.cancelled && match(image)
  }
  return [
    { id: "all", label: "All", match: () => true },
    ...SHAPE_TABS.map((shape) => ({
      id: shape.id,
      label: shape.label,
      hideWhenEmpty: true,
      match: (row: DataRow) =>
        live(row, (image) => image.check?.fits.some((type) => shape.types.includes(type)) ?? false),
    })),
    {
      id: "attention",
      label: "Needs Attention",
      hideWhenEmpty: true,
      match: (row) => live(row, (image) => Boolean(image.check?.problem)),
    },
  ]
}

function NameCell({ image }: { image: ImageRow }) {
  const name = image.check?.name ?? image.label
  return (
    <span className="flex min-w-0 items-center gap-2.5">
      <WorkspaceFileThumbnail
        className="size-8"
        fileId={image.id}
        kind="image"
        label={name}
        revisionId={image.check?.revisionId ?? null}
      />
      <span className="grid min-w-0 gap-0.5 text-sm">
        <span className="wrap-anywhere">{name}</span>
        {!image.cancelled && image.check?.problem ? (
          <span className="text-destructive text-xs wrap-anywhere">{image.check.problem}</span>
        ) : null}
        {!image.cancelled && !image.check ? (
          <span className="text-muted-foreground text-xs">Not checked yet.</span>
        ) : null}
      </span>
    </span>
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
