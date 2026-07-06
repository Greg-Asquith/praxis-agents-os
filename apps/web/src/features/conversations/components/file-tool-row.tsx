// apps/web/src/features/conversations/components/file-tool-row.tsx

import { FileIcon, FilePlus2Icon, FilesIcon, ImageIcon, SearchIcon } from "lucide-react"

import { FileCard } from "@/features/files/components/file-card"
import { FileContentView } from "@/features/files/components/file-content-view"
import {
  type ReadFileContentToolResult,
  type ReadFileImageToolResult,
  type ReadFileStatusToolResult,
  type ReadFileUrlToolResult,
  fileCardFromReadContentResult,
  fileCardFromReadImageResult,
  fileCardFromReadStatusResult,
  fileCardFromPromoteResult,
  fileCardFromRuntimeFile,
  fileCardFromReadUrlResult,
  fileCardFromWriteResult,
  listFilesResult,
  LIST_FILES_TOOL_NAME,
  PROMOTE_SCRATCH_TOOL_NAME,
  promoteScratchResult,
  readFileContentResult,
  readFileImageResult,
  readFileStatusResult,
  READ_FILE_TOOL_NAME,
  readFileUrlResult,
  WRITE_FILE_TOOL_NAME,
  writeFileContentArg,
  writeFileResult,
} from "@/features/conversations/file-tools"
import { TextBlock } from "@/features/conversations/components/tool-call-content-blocks"
import {
  ToolActivityRowHeader,
  ToolActivityRowShell,
} from "@/features/conversations/components/tool-activity-row-shell"
import {
  ActivityStatusIcon,
  ActivityStatusSuffix,
} from "@/features/conversations/components/tool-activity-status"
import { toolStatusSuffix } from "@/features/conversations/components/tool-activity-status-values"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { formatBytes, formatDateTime } from "@/lib/format"

type FileToolRowProps = {
  activity: ToolActivity
  compact: boolean
  defaultOpen: boolean
}

export function FileToolRow({ activity, compact, defaultOpen }: FileToolRowProps) {
  return renderFileToolRow({ activity, compact, defaultOpen })
}

function renderFileToolRow({ activity, compact, defaultOpen }: FileToolRowProps) {
  if (activity.name === LIST_FILES_TOOL_NAME) {
    return <ListFilesRow activity={activity} compact={compact} defaultOpen={defaultOpen} />
  }
  if (activity.name === WRITE_FILE_TOOL_NAME) {
    return <WriteFileRow activity={activity} compact={compact} defaultOpen={defaultOpen} />
  }
  if (activity.name === PROMOTE_SCRATCH_TOOL_NAME) {
    return <PromoteScratchRow activity={activity} compact={compact} defaultOpen={defaultOpen} />
  }
  if (activity.name === READ_FILE_TOOL_NAME) {
    return <ReadFileRow activity={activity} compact={compact} defaultOpen={defaultOpen} />
  }
  return null
}

function ListFilesRow({ activity, compact, defaultOpen }: FileToolRowProps) {
  const result = listFilesResult(activity.result)
  if (!result) {
    return null
  }

  const header = (
    <ToolActivityRowHeader
      expandable
      icon={<ActivityStatusIcon fallbackIcon="tool" status={activity.status} />}
      label={
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <FilesIcon className="text-muted-foreground size-3.5 shrink-0" />
          <span className="min-w-0 truncate">Listed Files</span>
        </span>
      }
      suffix={<ActivityStatusSuffix status={activity.status} suffix={toolStatusSuffix(activity)} />}
      supportLabel={null}
    />
  )

  return (
    <ToolActivityRowShell compact={compact} defaultOpen={defaultOpen} expandable header={header}>
      <TextBlock
        label="Summary"
        value={`${String(result.files.length)} workspace files · ${String(
          result.scratch.length
        )} drafts · ${String(result.total)} total files`}
      />
      {result.files.length > 0 ? (
        <div className="space-y-2">
          <p className="text-muted-foreground text-xs font-medium">Files</p>
          {result.files.map((file) => (
            <FileCard key={file.id} file={fileCardFromRuntimeFile(file)} />
          ))}
        </div>
      ) : null}
      {result.scratch.length > 0 ? (
        <div className="space-y-2">
          <p className="text-muted-foreground text-xs font-medium">Drafts</p>
          {result.scratch.map((entry) => (
            <TextBlock
              key={entry.name}
              label={entry.name}
              value={`${formatBytes(entry.content_bytes)} · kept until ${formatDateTime(
                entry.expires_at
              )}`}
            />
          ))}
        </div>
      ) : null}
    </ToolActivityRowShell>
  )
}

function WriteFileRow({ activity, compact, defaultOpen }: FileToolRowProps) {
  const result = writeFileResult(activity.result)
  if (!result) {
    return null
  }

  const file = fileCardFromWriteResult(result)
  const isScratch = result.destination === "scratch"
  const scratchContent = isScratch ? writeFileContentArg(activity.args) : null
  const label = isScratch ? `Drafted "${result.name}"` : "Wrote File"
  const expandable = Boolean(file) || isScratch
  const header = (
    <ToolActivityRowHeader
      expandable={expandable}
      icon={<ActivityStatusIcon fallbackIcon="tool" status={activity.status} />}
      label={
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <FilePlus2Icon className="text-muted-foreground size-3.5 shrink-0" />
          <span className="min-w-0 truncate">{label}</span>
        </span>
      }
      suffix={<ActivityStatusSuffix status={activity.status} suffix={toolStatusSuffix(activity)} />}
      supportLabel={null}
    />
  )

  return (
    <ToolActivityRowShell
      compact={compact}
      defaultOpen={defaultOpen}
      expandable={expandable}
      header={header}
    >
      {file ? <FileCard file={file} /> : null}
      {isScratch ? (
        <TextBlock
          label="Draft"
          value={`${result.name} · ${formatBytes(result.bytes_written)} · kept until ${
            result.expires_at ? formatDateTime(result.expires_at) : "later"
          }`}
        />
      ) : null}
      {scratchContent ? (
        <ContentBlock label="Content" name={result.name} value={scratchContent} />
      ) : null}
    </ToolActivityRowShell>
  )
}

function PromoteScratchRow({ activity, compact, defaultOpen }: FileToolRowProps) {
  const result = promoteScratchResult(activity.result)
  if (!result) {
    return null
  }

  const header = (
    <ToolActivityRowHeader
      expandable
      icon={<ActivityStatusIcon fallbackIcon="tool" status={activity.status} />}
      label={
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <FilePlus2Icon className="text-muted-foreground size-3.5 shrink-0" />
          <span className="min-w-0 truncate">Saved Draft to File</span>
        </span>
      }
      suffix={<ActivityStatusSuffix status={activity.status} suffix={toolStatusSuffix(activity)} />}
      supportLabel={null}
    />
  )

  return (
    <ToolActivityRowShell compact={compact} defaultOpen={defaultOpen} expandable header={header}>
      <FileCard file={fileCardFromPromoteResult(result)} />
    </ToolActivityRowShell>
  )
}

function ReadFileRow(props: FileToolRowProps) {
  const urlResult = readFileUrlResult(props.activity.result)
  if (urlResult) {
    return <ReadFileUrlRow {...props} result={urlResult} />
  }
  const contentResult = readFileContentResult(props.activity.result)
  if (contentResult) {
    return <ReadFileContentRow {...props} result={contentResult} />
  }
  const statusResult = readFileStatusResult(props.activity.result)
  if (statusResult) {
    return <ReadFileStatusRow {...props} result={statusResult} />
  }
  const imageResult = readFileImageResult(props.activity.result)
  if (imageResult) {
    return <ReadFileImageRow {...props} result={imageResult} />
  }
  return null
}

function ReadFileUrlRow({
  activity,
  compact,
  defaultOpen,
  result,
}: FileToolRowProps & { result: ReadFileUrlToolResult }) {
  const header = (
    <ToolActivityRowHeader
      expandable
      icon={<ActivityStatusIcon fallbackIcon="tool" status={activity.status} />}
      label={
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <FileIcon className="text-muted-foreground size-3.5 shrink-0" />
          <span className="min-w-0 truncate">Prepared Link</span>
        </span>
      }
      suffix={<ActivityStatusSuffix status={activity.status} suffix={toolStatusSuffix(activity)} />}
      supportLabel={null}
    />
  )

  return (
    <ToolActivityRowShell compact={compact} defaultOpen={defaultOpen} expandable header={header}>
      <FileCard file={fileCardFromReadUrlResult(result)} />
      <TextBlock label="Link expiry" value={formatDateTime(result.expires_at)} />
    </ToolActivityRowShell>
  )
}

function ReadFileContentRow({
  activity,
  compact,
  defaultOpen,
  result,
}: FileToolRowProps & { result: ReadFileContentToolResult }) {
  const file = fileCardFromReadContentResult(result)
  const isScratch = result.kind === "scratch" || (!result.file_id && Boolean(result.name))
  const label = isScratch
    ? result.name
      ? `Read the Draft ${result.name}`
      : "Read Draft"
    : "Read File"
  const header = (
    <ToolActivityRowHeader
      expandable
      icon={<ActivityStatusIcon fallbackIcon="tool" status={activity.status} />}
      label={
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <SearchIcon className="text-muted-foreground size-3.5 shrink-0" />
          <span className="min-w-0 truncate">{label}</span>
        </span>
      }
      suffix={<ActivityStatusSuffix status={activity.status} suffix={toolStatusSuffix(activity)} />}
      supportLabel={null}
    />
  )

  return (
    <ToolActivityRowShell compact={compact} defaultOpen={defaultOpen} expandable header={header}>
      {file ? <FileCard file={file} /> : null}
      {isScratch && result.name ? (
        <TextBlock
          label="Draft"
          value={`${result.name}${result.expires_at ? ` · kept until ${formatDateTime(result.expires_at)}` : ""}`}
        />
      ) : null}
      <TextBlock
        label="Byte range"
        value={`${String(result.offset)}-${String(result.end_offset)} of ${formatBytes(
          result.total_bytes
        )}${result.truncated ? " · truncated" : ""}`}
      />
      {result.source ? <TextBlock label="Source" value={result.source} /> : null}
      <ContentBlock
        label="Content"
        mediaType={result.media_type ?? null}
        name={result.name ?? null}
        value={result.content}
      />
      {result.hint ? <TextBlock label="Next read" value={result.hint} /> : null}
    </ToolActivityRowShell>
  )
}

function ReadFileStatusRow({
  activity,
  compact,
  defaultOpen,
  result,
}: FileToolRowProps & { result: ReadFileStatusToolResult }) {
  const header = (
    <ToolActivityRowHeader
      expandable
      icon={<ActivityStatusIcon fallbackIcon="tool" status={activity.status} />}
      label={
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <FileIcon className="text-muted-foreground size-3.5 shrink-0" />
          <span className="min-w-0 truncate">Checked File</span>
        </span>
      }
      suffix={<ActivityStatusSuffix status={activity.status} suffix={toolStatusSuffix(activity)} />}
      supportLabel={null}
    />
  )

  return (
    <ToolActivityRowShell compact={compact} defaultOpen={defaultOpen} expandable header={header}>
      <FileCard file={fileCardFromReadStatusResult(result)} />
      <TextBlock label="Status" value={`${result.status}: ${result.message}`} />
    </ToolActivityRowShell>
  )
}

function ReadFileImageRow({
  activity,
  compact,
  defaultOpen,
  result,
}: FileToolRowProps & { result: ReadFileImageToolResult }) {
  const header = (
    <ToolActivityRowHeader
      expandable
      icon={<ActivityStatusIcon fallbackIcon="tool" status={activity.status} />}
      label={
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <ImageIcon className="text-muted-foreground size-3.5 shrink-0" />
          <span className="min-w-0 truncate">Read image</span>
        </span>
      }
      suffix={<ActivityStatusSuffix status={activity.status} suffix={toolStatusSuffix(activity)} />}
      supportLabel={null}
    />
  )

  return (
    <ToolActivityRowShell compact={compact} defaultOpen={defaultOpen} expandable header={header}>
      <FileCard file={fileCardFromReadImageResult(result)} />
      <TextBlock label="Result" value="Image bytes were passed to the model." />
    </ToolActivityRowShell>
  )
}

function ContentBlock({
  label,
  mediaType,
  name,
  value,
}: {
  label: string
  mediaType?: string | null
  name?: string | null
  value: string
}) {
  return (
    <div className="min-w-0">
      <p className="text-muted-foreground mb-1 text-xs font-medium">{label}</p>
      <FileContentView content={value} mediaType={mediaType ?? null} name={name ?? null} />
    </div>
  )
}
