// apps/web/src/features/conversations/components/file-tool-row.tsx

import {
  FileIcon,
  FilePlus2Icon,
  FilesIcon,
  FileTextIcon,
  ImageIcon,
  SearchIcon,
} from "lucide-react"

import { FileContentView } from "@/features/files/components/file-content-view"
import {
  type ReadFileContentToolResult,
  type ReadFileImageToolResult,
  type ReadFileStatusToolResult,
  type ReadFileUrlToolResult,
  fileEntityFromReadContentResult,
  fileEntityFromReadImageResult,
  fileEntityFromReadStatusResult,
  fileEntityFromPromoteResult,
  fileEntityFromRuntimeFile,
  fileEntityFromReadUrlResult,
  fileEntityFromWriteResult,
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
import { FileEntityRow } from "@/features/conversations/components/file-entity-row"
import { ToolField } from "@/features/conversations/components/tool-field"
import {
  ToolActivityRowHeader,
  ToolActivityRowShell,
} from "@/features/conversations/components/tool-activity-row-shell"
import {
  ActivityStatusIcon,
  ActivityStatusSuffix,
} from "@/features/conversations/components/tool-activity-status"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { formatBytes, formatDateTime, pluralize } from "@/lib/format"

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
          <span className="min-w-0 truncate">Found Files</span>
        </span>
      }
      suffix={
        <ActivityStatusSuffix
          status={activity.status}
          suffix={`${String(result.total)} ${pluralize(result.total, "file")}`}
        />
      }
      supportLabel={null}
    />
  )

  return (
    <ToolActivityRowShell compact={compact} defaultOpen={defaultOpen} expandable header={header}>
      <ToolField
        field={{
          key: "files",
          label: `Files · ${String(result.files.length)}`,
          value: "",
          format: "text",
        }}
      >
        {result.files.length > 0 ? (
          <div className="divide-border -my-1 divide-y">
            {result.files.map((file) => (
              <FileEntityRow file={fileEntityFromRuntimeFile(file)} key={file.id} />
            ))}
          </div>
        ) : (
          <p className="text-muted-foreground py-1 text-xs">No workspace files found.</p>
        )}
      </ToolField>
      {result.scratch.length > 0 ? (
        <ToolField
          field={{
            key: "drafts",
            label: `Drafts · ${String(result.scratch.length)}`,
            value: "",
            format: "text",
          }}
        >
          <div className="divide-border -my-1 divide-y">
            {result.scratch.map((entry) => (
              <div className="flex min-w-0 items-center gap-2.5 px-1.5 py-2" key={entry.name}>
                <span className="bg-muted text-muted-foreground flex size-9 shrink-0 items-center justify-center rounded-md border">
                  <FileTextIcon className="size-4" />
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">{entry.name}</span>
                  <span className="text-muted-foreground block truncate text-xs">
                    {formatBytes(entry.content_bytes)} · Updated {formatDateTime(entry.updated_at)}{" "}
                    · Kept until {formatDateTime(entry.expires_at)}
                  </span>
                </span>
              </div>
            ))}
          </div>
        </ToolField>
      ) : null}
    </ToolActivityRowShell>
  )
}

function WriteFileRow({ activity, compact, defaultOpen }: FileToolRowProps) {
  const result = writeFileResult(activity.result)
  if (!result) {
    return null
  }

  const file = fileEntityFromWriteResult(result)
  const isScratch = result.destination === "scratch"
  const scratchContent = isScratch ? writeFileContentArg(activity.args) : null
  const label = isScratch ? `Saved Draft ${result.name}` : `Saved ${result.name} to Your Files`
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
      suffix={
        <ActivityStatusSuffix status={activity.status} suffix={formatBytes(result.bytes_written)} />
      }
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
      {file ? <FileOutcomeField file={file} /> : null}
      {isScratch ? (
        <ToolField
          field={{
            key: "draft",
            label: "Draft",
            value: `${result.name} · ${formatBytes(result.bytes_written)} · kept until ${
              result.expires_at ? formatDateTime(result.expires_at) : "later"
            }`,
            format: "text",
          }}
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
          <span className="min-w-0 truncate">Saved {result.name} to Your Files</span>
        </span>
      }
      suffix={<ActivityStatusSuffix status={activity.status} suffix={result.name} />}
      supportLabel={null}
    />
  )

  return (
    <ToolActivityRowShell compact={compact} defaultOpen={defaultOpen} expandable header={header}>
      <FileOutcomeField file={fileEntityFromPromoteResult(result)} />
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
          <span className="min-w-0 truncate">Loaded File</span>
        </span>
      }
      suffix={<ActivityStatusSuffix status={activity.status} suffix={result.name} />}
      supportLabel={null}
    />
  )

  return (
    <ToolActivityRowShell compact={compact} defaultOpen={defaultOpen} expandable header={header}>
      <FileOutcomeField file={fileEntityFromReadUrlResult(result)} />
      <ToolField
        field={{
          key: "expires_at",
          label: "Link Available Until",
          value: formatDateTime(result.expires_at),
          format: "datetime",
        }}
      />
    </ToolActivityRowShell>
  )
}

function ReadFileContentRow({
  activity,
  compact,
  defaultOpen,
  result,
}: FileToolRowProps & { result: ReadFileContentToolResult }) {
  const file = fileEntityFromReadContentResult(result)
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
      suffix={
        <ActivityStatusSuffix
          status={activity.status}
          suffix={formatBytes(result.end_offset - result.offset)}
        />
      }
      supportLabel={null}
    />
  )

  return (
    <ToolActivityRowShell compact={compact} defaultOpen={defaultOpen} expandable header={header}>
      {file ? <FileOutcomeField file={file} /> : null}
      {isScratch && result.name ? (
        <ToolField
          field={{
            key: "draft",
            label: "Draft",
            value: `${result.name}${result.expires_at ? ` · kept until ${formatDateTime(result.expires_at)}` : ""}`,
            format: "text",
          }}
        />
      ) : null}
      <ToolField
        field={{
          key: "content_read",
          label: "Content Read",
          value: `${formatBytes(result.end_offset - result.offset)} of ${formatBytes(
            result.total_bytes
          )}${result.truncated ? " · more available" : ""}`,
          format: "text",
        }}
      />
      <ContentBlock
        label="Content"
        mediaType={result.media_type ?? null}
        name={result.name ?? null}
        value={result.content}
      />
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
      suffix={<ActivityStatusSuffix status={activity.status} suffix={result.name} />}
      supportLabel={null}
    />
  )

  return (
    <ToolActivityRowShell compact={compact} defaultOpen={defaultOpen} expandable header={header}>
      <FileOutcomeField file={fileEntityFromReadStatusResult(result)} />
      <ToolField
        field={{
          key: "status",
          label: "File Status",
          value: result.message,
          format: "multiline",
        }}
      />
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
          <span className="min-w-0 truncate">Read Image</span>
        </span>
      }
      suffix={<ActivityStatusSuffix status={activity.status} suffix={result.name} />}
      supportLabel={null}
    />
  )

  return (
    <ToolActivityRowShell compact={compact} defaultOpen={defaultOpen} expandable header={header}>
      <FileOutcomeField file={fileEntityFromReadImageResult(result)} />
      <ToolField
        field={{
          key: "result",
          label: "Result",
          value: "The image was shared with the agent.",
          format: "text",
        }}
      />
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
    <ToolField field={{ key: "content", label, value, format: "multiline" }}>
      <FileContentView content={value} mediaType={mediaType ?? null} name={name ?? null} />
    </ToolField>
  )
}

function FileOutcomeField({ file }: { file: Parameters<typeof FileEntityRow>[0]["file"] }) {
  return (
    <ToolField field={{ key: "file", label: "File", value: "", format: "text" }}>
      <FileEntityRow file={file} />
    </ToolField>
  )
}
