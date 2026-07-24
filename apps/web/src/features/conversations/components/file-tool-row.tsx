// apps/web/src/features/conversations/components/file-tool-row.tsx

import {
  FileIcon,
  FilePlus2Icon,
  FilesIcon,
  FileTextIcon,
  ImageIcon,
  SearchIcon,
  type LucideIcon,
} from "lucide-react"
import type { ReactNode } from "react"

import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { ToolResultCard, type ToolResultDetail } from "@/components/tool-ui/result-card"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { FileEntityRow } from "@/features/conversations/components/file-entity-row"
import { ActivityStatusBadge } from "@/features/conversations/components/tool-activity-status"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  type ReadFileContentToolResult,
  type ReadFileImageToolResult,
  type ReadFileStatusToolResult,
  type ReadFileUrlToolResult,
  fileEntityFromPromoteResult,
  fileEntityFromReadContentResult,
  fileEntityFromReadImageResult,
  fileEntityFromReadStatusResult,
  fileEntityFromReadUrlResult,
  fileEntityFromRuntimeFile,
  fileEntityFromWriteResult,
  listFilesResult,
  LIST_FILES_TOOL_NAME,
  promoteScratchResult,
  PROMOTE_SCRATCH_TOOL_NAME,
  readFileContentResult,
  readFileImageResult,
  readFileStatusResult,
  READ_FILE_TOOL_NAME,
  readFileUrlResult,
  writeFileContentArg,
  writeFileResult,
  WRITE_FILE_TOOL_NAME,
} from "@/features/conversations/native-tools/file-tools"
import { FileContentView } from "@/features/files/components/file-content-view"
import { formatBytes, formatDateTime, pluralize } from "@/lib/format"

type FileToolRowProps = {
  activity: ToolActivity
  defaultOpen: boolean
}

export function FileToolRow({ activity, defaultOpen }: FileToolRowProps) {
  if (activity.status === "running" || activity.status === "awaiting_approval") {
    const state = filePendingState(activity.name)
    return state ? (
      <FanOutSkeleton
        heading={<FileToolHeading icon={state.icon}>{state.heading}</FileToolHeading>}
        label={activity.status === "running" ? state.runningLabel : state.waitingLabel}
      />
    ) : null
  }
  if (
    activity.status === "failed" ||
    activity.status === "denied" ||
    activity.status === "unknown"
  ) {
    return <FileFailureRow activity={activity} />
  }
  if (activity.name === LIST_FILES_TOOL_NAME) {
    return <ListFilesRow activity={activity} defaultOpen={defaultOpen} />
  }
  if (activity.name === WRITE_FILE_TOOL_NAME) {
    return <WriteFileRow activity={activity} defaultOpen={defaultOpen} />
  }
  if (activity.name === PROMOTE_SCRATCH_TOOL_NAME) {
    return <PromoteScratchRow activity={activity} defaultOpen={defaultOpen} />
  }
  if (activity.name === READ_FILE_TOOL_NAME) {
    return <ReadFileRow activity={activity} defaultOpen={defaultOpen} />
  }
  return null
}

function ListFilesRow({
  activity,
  defaultOpen,
}: Pick<FileToolRowProps, "activity" | "defaultOpen">) {
  const result = listFilesResult(activity.result)
  if (!result) {
    return null
  }

  const countLabel = `${String(result.total)} ${pluralize(result.total, "File")}`
  const draftDetails = result.scratch.map((entry) => ({
    label: `Draft · ${entry.name}`,
    summary: false,
    value: `${formatBytes(entry.content_bytes)} · Updated ${formatDateTime(entry.updated_at)} · Kept until ${formatDateTime(entry.expires_at)}`,
  }))
  return (
    <ToolResultCard
      ariaLabel="Workspace files"
      defaultOpen={defaultOpen}
      details={[
        { label: "Files", value: countLabel },
        { label: "Drafts", value: String(result.scratch.length) },
        ...draftDetails,
      ]}
      heading={<FileToolHeading icon={FilesIcon}>Workspace Files</FileToolHeading>}
      trailing={<Badge variant="success">{countLabel}</Badge>}
    >
      <div className="grid min-w-0 gap-4">
        {result.files.length > 0 ? (
          <div className="divide-border divide-y" role="list">
            {result.files.map((file) => (
              <div key={file.id} role="listitem">
                <FileEntityRow file={fileEntityFromRuntimeFile(file)} />
              </div>
            ))}
          </div>
        ) : (
          <p className="text-muted-foreground px-4 py-6 text-center text-sm">
            No workspace files found.
          </p>
        )}
        {result.scratch.length > 0 ? (
          <div className="border-border/70 overflow-hidden rounded-lg border">
            <p className="bg-muted/25 border-b px-3 py-2 text-xs font-medium">
              Drafts · {String(result.scratch.length)}
            </p>
            <div className="divide-border divide-y">
              {result.scratch.map((entry) => (
                <div className="flex min-w-0 items-center gap-2.5 px-3 py-2" key={entry.name}>
                  <span className="bg-muted text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-md border">
                    <FileTextIcon className="size-4" />
                  </span>
                  <span className="min-w-0 truncate text-sm font-medium">{entry.name}</span>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </ToolResultCard>
  )
}

function WriteFileRow({
  activity,
  defaultOpen,
}: Pick<FileToolRowProps, "activity" | "defaultOpen">) {
  const result = writeFileResult(activity.result)
  if (!result) {
    return null
  }

  const file = fileEntityFromWriteResult(result)
  const isScratch = result.destination === "scratch"
  const scratchContent = isScratch ? writeFileContentArg(activity.args) : null
  const heading = isScratch ? "Save Draft" : "Save File"
  return (
    <ToolResultCard
      ariaLabel={isScratch ? `Saved draft ${result.name}` : `Saved file ${result.name}`}
      defaultOpen={defaultOpen}
      details={[
        { label: isScratch ? "Draft" : "File", value: result.name },
        { label: "Size", value: formatBytes(result.bytes_written) },
        ...(result.expires_at
          ? [{ label: "Kept Until", value: formatDateTime(result.expires_at) }]
          : []),
      ]}
      heading={<FileToolHeading icon={FilePlus2Icon}>{heading}</FileToolHeading>}
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      <div className="grid min-w-0 gap-3">
        {file ? <FileEntityRow file={file} /> : null}
        {isScratch ? (
          <p className="text-muted-foreground text-sm">
            Saved {result.name} as a temporary draft
            {result.expires_at ? ` until ${formatDateTime(result.expires_at)}` : ""}.
          </p>
        ) : null}
        {scratchContent ? <FileContentBlock name={result.name} value={scratchContent} /> : null}
      </div>
    </ToolResultCard>
  )
}

function PromoteScratchRow({
  activity,
  defaultOpen,
}: Pick<FileToolRowProps, "activity" | "defaultOpen">) {
  const result = promoteScratchResult(activity.result)
  if (!result) {
    return null
  }

  return (
    <ToolResultCard
      ariaLabel={`Saved ${result.name} to workspace files`}
      defaultOpen={defaultOpen}
      details={[
        { label: "File", value: result.name },
        { label: "Draft Removed", value: result.deleted_scratch ? "Yes" : "No" },
      ]}
      heading={<FileToolHeading icon={FilePlus2Icon}>Save Draft to Files</FileToolHeading>}
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      <FileEntityRow file={fileEntityFromPromoteResult(result)} />
    </ToolResultCard>
  )
}

function ReadFileRow({
  activity,
  defaultOpen,
}: Pick<FileToolRowProps, "activity" | "defaultOpen">) {
  const urlResult = readFileUrlResult(activity.result)
  if (urlResult) {
    return <ReadFileUrlRow activity={activity} defaultOpen={defaultOpen} result={urlResult} />
  }
  const contentResult = readFileContentResult(activity.result)
  if (contentResult) {
    return (
      <ReadFileContentRow activity={activity} defaultOpen={defaultOpen} result={contentResult} />
    )
  }
  const statusResult = readFileStatusResult(activity.result)
  if (statusResult) {
    return <ReadFileStatusRow activity={activity} defaultOpen={defaultOpen} result={statusResult} />
  }
  const imageResult = readFileImageResult(activity.result)
  if (imageResult) {
    return <ReadFileImageRow activity={activity} defaultOpen={defaultOpen} result={imageResult} />
  }
  return null
}

function ReadFileUrlRow({
  activity,
  defaultOpen,
  result,
}: Pick<FileToolRowProps, "activity" | "defaultOpen"> & { result: ReadFileUrlToolResult }) {
  return (
    <ReadFileCard
      activity={activity}
      defaultOpen={defaultOpen}
      details={[
        { label: "File", value: result.name },
        { label: "Link Available Until", value: formatDateTime(result.expires_at) },
      ]}
      heading="Load File"
      icon={FileIcon}
    >
      <FileEntityRow file={fileEntityFromReadUrlResult(result)} />
    </ReadFileCard>
  )
}

function ReadFileContentRow({
  activity,
  defaultOpen,
  result,
}: Pick<FileToolRowProps, "activity" | "defaultOpen"> & { result: ReadFileContentToolResult }) {
  const file = fileEntityFromReadContentResult(result)
  const isScratch = result.kind === "scratch" || (!result.file_id && Boolean(result.name))
  const bytesRead = result.end_offset - result.offset
  return (
    <ReadFileCard
      activity={activity}
      defaultOpen={defaultOpen}
      details={[
        ...(result.name ? [{ label: isScratch ? "Draft" : "File", value: result.name }] : []),
        {
          label: "Content Read",
          value: `${formatBytes(bytesRead)} of ${formatBytes(result.total_bytes)}`,
        },
        {
          label: "Range",
          value: `${String(result.offset)}–${String(result.end_offset)} bytes`,
        },
        ...(result.expires_at
          ? [{ label: "Kept Until", value: formatDateTime(result.expires_at), summary: false }]
          : []),
      ]}
      heading={isScratch ? "Read Draft" : "Read File"}
      icon={SearchIcon}
    >
      <div className="grid min-w-0 gap-3">
        {file ? <FileEntityRow file={file} /> : null}
        {result.truncated ? (
          <p className="text-muted-foreground text-xs">
            This view is truncated. More content is available.
          </p>
        ) : null}
        {result.hint ? <p className="text-muted-foreground text-xs">{result.hint}</p> : null}
        <FileContentBlock
          mediaType={result.media_type ?? null}
          name={result.name ?? null}
          value={result.content}
        />
      </div>
    </ReadFileCard>
  )
}

function ReadFileStatusRow({
  activity,
  defaultOpen,
  result,
}: Pick<FileToolRowProps, "activity" | "defaultOpen"> & { result: ReadFileStatusToolResult }) {
  return (
    <ReadFileCard
      activity={activity}
      defaultOpen={defaultOpen}
      details={[
        { label: "File", value: result.name },
        { label: "File Status", value: result.status },
      ]}
      heading="Check File"
      icon={FileIcon}
    >
      <div className="grid min-w-0 gap-3">
        <FileEntityRow file={fileEntityFromReadStatusResult(result)} />
        <p className="text-muted-foreground text-sm whitespace-pre-wrap">{result.message}</p>
      </div>
    </ReadFileCard>
  )
}

function ReadFileImageRow({
  activity,
  defaultOpen,
  result,
}: Pick<FileToolRowProps, "activity" | "defaultOpen"> & { result: ReadFileImageToolResult }) {
  return (
    <ReadFileCard
      activity={activity}
      defaultOpen={defaultOpen}
      details={[{ label: "Image", value: result.name }]}
      heading="Read Image"
      icon={ImageIcon}
    >
      <div className="grid min-w-0 gap-3">
        <FileEntityRow file={fileEntityFromReadImageResult(result)} />
        <p className="text-muted-foreground text-sm">The image was shared with the agent.</p>
      </div>
    </ReadFileCard>
  )
}

function ReadFileCard({
  activity,
  children,
  defaultOpen,
  details,
  heading,
  icon,
}: Pick<FileToolRowProps, "activity" | "defaultOpen"> & {
  children: ReactNode
  details: ToolResultDetail[]
  heading: string
  icon: LucideIcon
}) {
  return (
    <ToolResultCard
      ariaLabel={heading}
      defaultOpen={defaultOpen}
      details={details}
      heading={<FileToolHeading icon={icon}>{heading}</FileToolHeading>}
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      {children}
    </ToolResultCard>
  )
}

function FileFailureRow({ activity }: Pick<FileToolRowProps, "activity">) {
  const state = filePendingState(activity.name)
  if (!state) {
    return null
  }
  const message =
    typeof activity.result === "string" && activity.result.trim()
      ? activity.result
      : activity.status === "denied"
        ? "This file action was declined. Nothing was changed."
        : "The file action did not finish. No result was confirmed."
  return (
    <ToolResultCard
      ariaLabel={`${state.heading} failed`}
      defaultOpen
      details={[{ label: "Action", value: state.heading }]}
      heading={<FileToolHeading icon={state.icon}>{state.heading}</FileToolHeading>}
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      <Alert variant="destructive">
        <AlertTitle>
          {activity.status === "denied" ? "Action Declined" : "What Went Wrong"}
        </AlertTitle>
        <AlertDescription className="whitespace-pre-wrap">{message}</AlertDescription>
      </Alert>
    </ToolResultCard>
  )
}

function FileContentBlock({
  mediaType,
  name,
  value,
}: {
  mediaType?: string | null
  name?: string | null
  value: string
}) {
  return (
    <div className="border-border/70 overflow-hidden rounded-lg border">
      <p className="bg-muted/25 border-b px-3 py-2 text-xs font-medium">Content</p>
      <FileContentView content={value} mediaType={mediaType ?? null} name={name ?? null} />
    </div>
  )
}

function FileToolHeading({ children, icon: Icon }: { children: string; icon: LucideIcon }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <Icon className="text-muted-foreground size-4 shrink-0" />
      <span className="truncate">{children}</span>
    </span>
  )
}

function filePendingState(name: string) {
  if (name === LIST_FILES_TOOL_NAME) {
    return {
      heading: "Workspace Files",
      icon: FilesIcon,
      runningLabel: "Listing files…",
      waitingLabel: "Waiting to list files…",
    }
  }
  if (name === WRITE_FILE_TOOL_NAME) {
    return {
      heading: "Save File",
      icon: FilePlus2Icon,
      runningLabel: "Saving file…",
      waitingLabel: "Waiting to save file…",
    }
  }
  if (name === PROMOTE_SCRATCH_TOOL_NAME) {
    return {
      heading: "Save Draft to Files",
      icon: FilePlus2Icon,
      runningLabel: "Saving draft…",
      waitingLabel: "Waiting to save draft…",
    }
  }
  if (name === READ_FILE_TOOL_NAME) {
    return {
      heading: "Read File",
      icon: SearchIcon,
      runningLabel: "Reading file…",
      waitingLabel: "Waiting to read file…",
    }
  }
  return null
}
