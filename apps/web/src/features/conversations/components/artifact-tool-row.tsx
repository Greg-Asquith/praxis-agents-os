// apps/web/src/features/conversations/components/artifact-tool-row.tsx

import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  ExternalLinkIcon,
  FileCode2Icon,
  FilesIcon,
  FileTextIcon,
  ImageIcon,
  RefreshCwIcon,
  Table2Icon,
  WorkflowIcon,
  type LucideIcon,
} from "lucide-react"

import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { createArtifactViewUrl } from "@/features/artifacts/api/create-view-url"
import { artifactQueryOptions } from "@/features/artifacts/api/get-artifact"
import { artifactVersionContentQueryOptions } from "@/features/artifacts/api/get-artifact-version-content"
import { ArtifactPreviewFrame } from "@/features/artifacts/components/artifact-preview-frame"
import { ArtifactVersionSelector } from "@/features/artifacts/components/artifact-version-selector"
import { artifactTypeLabel } from "@/features/artifacts/format"
import type { ArtifactType } from "@/features/artifacts/types"
import { ActivityStatusBadge } from "@/features/conversations/components/tool-activity-status"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  CREATE_ARTIFACT_TOOL_NAME,
  LIST_ARTIFACTS_TOOL_NAME,
  READ_ARTIFACT_TOOL_NAME,
  UPDATE_ARTIFACT_TOOL_NAME,
  type ArtifactToolSummary,
  artifactListToolResult,
  artifactReadToolResult,
  artifactReferenceArg,
  artifactSearchArg,
  artifactTitleArg,
  artifactToolResult,
} from "@/features/conversations/native-tools/artifact-tools"
import { getErrorMessage } from "@/lib/api/errors"
import { formatBytes, formatCompactDate, pluralize } from "@/lib/format"
import { openSignedResource } from "@/lib/open-signed-resource"

type ArtifactToolRowProps = {
  activity: ToolActivity
  defaultOpen: boolean
}

export function ArtifactToolRow({ activity, defaultOpen }: ArtifactToolRowProps) {
  const state = artifactState(activity.name)
  if (!state) {
    return null
  }
  if (activity.status === "running" || activity.status === "awaiting_approval") {
    const summary = artifactPendingSummary(activity)
    return (
      <FanOutSkeleton
        heading={<ArtifactHeading icon={state.icon}>{state.heading}</ArtifactHeading>}
        label={activity.status === "running" ? state.runningLabel : state.waitingLabel}
        {...(summary ? { summary } : {})}
      />
    )
  }
  if (
    activity.status === "failed" ||
    activity.status === "denied" ||
    activity.status === "unknown"
  ) {
    return <ArtifactFailureRow activity={activity} state={state} />
  }

  if (activity.name === LIST_ARTIFACTS_TOOL_NAME) {
    return <ArtifactListRow activity={activity} defaultOpen={defaultOpen} />
  }
  if (activity.name === READ_ARTIFACT_TOOL_NAME) {
    return <ArtifactReadRow activity={activity} defaultOpen={defaultOpen} />
  }

  const result = artifactToolResult(activity.result)
  return result ? (
    <CompletedArtifactRow
      activity={activity}
      defaultOpen={defaultOpen}
      result={result}
      state={state}
    />
  ) : null
}

function ArtifactListRow({ activity, defaultOpen }: ArtifactToolRowProps) {
  const result = artifactListToolResult(activity.result)
  if (!result) {
    return null
  }
  const search = artifactSearchArg(activity.args)
  const resultLabel = `${String(result.total)} ${pluralize(result.total, "Artifact")}`
  return (
    <ToolResultCard
      ariaLabel={search ? `Artifacts matching ${search}` : "Workspace artifacts"}
      defaultOpen={defaultOpen}
      details={[
        ...(search ? [{ label: "Search", value: search }] : []),
        { label: "Found", value: String(result.total) },
        ...(result.returned < result.total
          ? [{ label: "Showing", summary: false, value: String(result.returned) }]
          : []),
      ]}
      heading={<ArtifactHeading icon={FilesIcon}>Artifacts</ArtifactHeading>}
      trailing={<Badge variant="success">{resultLabel}</Badge>}
    >
      {result.items.length > 0 ? (
        <ol aria-label="Artifact results" className="divide-border divide-y rounded-lg border">
          {result.items.map((artifact) => (
            <ArtifactSummaryItem artifact={artifact} key={artifact.reference.entity_id} />
          ))}
        </ol>
      ) : (
        <p className="text-muted-foreground px-4 py-6 text-center text-sm">
          {search ? "No artifacts matched this search." : "This workspace has no artifacts yet."}
        </p>
      )}
    </ToolResultCard>
  )
}

function ArtifactSummaryItem({ artifact }: { artifact: ArtifactToolSummary }) {
  return (
    <li className="flex min-w-0 items-center gap-3 px-3 py-2.5">
      <span className="bg-primary/8 text-primary flex size-9 shrink-0 items-center justify-center rounded-md">
        <ArtifactTypeIcon type={artifact.artifact_type} />
      </span>
      <span className="min-w-0 flex-1">
        <ArtifactEntityLink artifactId={artifact.reference.entity_id} title={artifact.title} />
        <span className="text-muted-foreground block truncate text-xs">
          {String(artifact.version_count)} {pluralize(artifact.version_count, "version")} · Updated{" "}
          {formatCompactDate(artifact.updated_at)}
        </span>
      </span>
      <Badge variant="secondary">{artifactTypeLabel(artifact.artifact_type)}</Badge>
    </li>
  )
}

function ArtifactReadRow({ activity, defaultOpen }: ArtifactToolRowProps) {
  const result = artifactReadToolResult(activity.result)
  if (!result) {
    return null
  }
  return (
    <ToolResultCard
      ariaLabel={`Read artifact ${result.title}`}
      defaultOpen={defaultOpen}
      details={[
        { label: "Artifact", value: result.title },
        { label: "Revision", value: String(result.revision_number) },
        { label: "Size", value: formatBytes(result.size_bytes) },
        { label: "Updated", summary: false, value: formatCompactDate(result.updated_at) },
      ]}
      heading={<ArtifactHeading icon={FileTextIcon}>Read Artifact</ArtifactHeading>}
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      <div className="grid min-w-0 gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="bg-primary/8 text-primary flex size-9 shrink-0 items-center justify-center rounded-md">
            <ArtifactTypeIcon type={result.artifact_type} />
          </span>
          <span className="min-w-0 flex-1">
            <ArtifactEntityLink artifactId={result.reference.entity_id} title={result.title} />
            <span className="text-muted-foreground block truncate text-xs">
              {artifactTypeLabel(result.artifact_type)} · Revision {String(result.revision_number)}
            </span>
          </span>
          <Badge variant="secondary">{artifactTypeLabel(result.artifact_type)}</Badge>
        </div>
        {result.truncated ? (
          <p className="text-muted-foreground text-xs">
            Showing the first part of this artifact. Open it to view the complete version.
          </p>
        ) : null}
        <Tabs className="min-w-0 gap-2" defaultValue="rendered">
          <TabsList aria-label="Artifact content view" className="self-start" variant="micro">
            <TabsTrigger value="rendered">Rendered</TabsTrigger>
            <TabsTrigger value="raw">Raw</TabsTrigger>
          </TabsList>
          <TabsContent value="rendered">
            {result.content === null ? (
              <ArtifactBinaryContent />
            ) : (
              <ArtifactPreviewFrame
                artifactType={result.artifact_type}
                content={{
                  content: result.content,
                  content_type: result.content_type,
                  download_url: null,
                  size_bytes: result.size_bytes,
                }}
                title={`${result.title} rendered preview`}
                versionId={`${result.id}:${String(result.revision_number)}`}
              />
            )}
          </TabsContent>
          <TabsContent value="raw">
            {result.content === null ? (
              <ArtifactBinaryContent />
            ) : (
              <div className="border-border overflow-hidden rounded-lg border">
                <pre className="max-h-96 min-w-0 overflow-auto px-3 py-2 font-mono text-xs leading-5 wrap-break-word whitespace-pre-wrap">
                  {result.content}
                </pre>
              </div>
            )}
          </TabsContent>
        </Tabs>
      </div>
    </ToolResultCard>
  )
}

function ArtifactBinaryContent() {
  return (
    <div className="border-border bg-muted/20 rounded-lg border px-3 py-5 text-center">
      <p className="text-sm font-medium">Preview this image in Artifacts</p>
      <p className="text-muted-foreground mt-1 text-xs">
        Binary artifact content is not included in the conversation.
      </p>
    </div>
  )
}

function CompletedArtifactRow({
  activity,
  defaultOpen,
  result,
  state,
}: ArtifactToolRowProps & {
  result: NonNullable<ReturnType<typeof artifactToolResult>>
  state: ArtifactState
}) {
  const [opening, setOpening] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleOpen() {
    setError(null)
    setOpening(true)
    try {
      await openSignedResource(async () => {
        const grant = await createArtifactViewUrl(result.artifact_id, result.version_id)
        return grant.url
      })
    } catch (openError) {
      setError(getErrorMessage(openError))
    } finally {
      setOpening(false)
    }
  }

  return (
    <ToolResultCard
      ariaLabel={`${state.pastTense} artifact ${result.title}`}
      defaultOpen={defaultOpen}
      details={[
        { label: "Artifact", value: result.title },
        { label: "Type", value: artifactTypeLabel(result.artifact_type) },
        { label: "Action", value: state.pastTense },
      ]}
      heading={<ArtifactHeading icon={state.icon}>{state.heading}</ArtifactHeading>}
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      <div className="grid min-w-0 gap-2">
        <div className="border-border bg-background/70 flex min-w-0 items-center gap-3 rounded-lg border p-2.5">
          <span className="bg-primary/8 text-primary flex size-9 shrink-0 items-center justify-center rounded-md">
            <ArtifactTypeIcon type={result.artifact_type} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium">{result.title}</span>
            <span className="text-muted-foreground block truncate text-xs">
              {artifactTypeLabel(result.artifact_type)} artifact
            </span>
          </span>
          <Badge variant="secondary">{artifactTypeLabel(result.artifact_type)}</Badge>
          <Button
            render={
              <a
                aria-label={`Manage artifact ${result.title}`}
                href={`/artifacts/${result.artifact_id}`}
              />
            }
            size="sm"
            variant="ghost"
          >
            Manage
          </Button>
          <Button
            aria-label={`Open artifact ${result.title}`}
            disabled={opening}
            onClick={() => {
              void handleOpen()
            }}
            size="sm"
            type="button"
            variant="outline"
          >
            <ExternalLinkIcon data-icon="inline-start" />
            {opening ? "Opening…" : "Open"}
          </Button>
        </div>
        <InlineArtifactPreview
          artifactId={result.artifact_id}
          initialVersionId={result.version_id}
          title={result.title}
        />
        {error ? (
          <p className="text-destructive text-xs" role="alert">
            {error}
          </p>
        ) : null}
      </div>
    </ToolResultCard>
  )
}

function InlineArtifactPreview({
  artifactId,
  initialVersionId,
  title,
}: {
  artifactId: string
  initialVersionId: string
  title: string
}) {
  const [versionId, setVersionId] = useState(initialVersionId)
  const artifactQuery = useQuery(artifactQueryOptions(artifactId))
  const contentQuery = useQuery(artifactVersionContentQueryOptions(artifactId, versionId))
  if (artifactQuery.isError || contentQuery.isError) {
    return (
      <p className="text-muted-foreground text-xs">
        Preview unavailable. Open the artifact to inspect it.
      </p>
    )
  }
  if (!artifactQuery.data || !contentQuery.data) {
    return <div className="bg-muted/30 h-28 animate-pulse rounded-lg" />
  }
  return (
    <div className="grid gap-2">
      {artifactQuery.data.versions.length > 1 ? (
        <ArtifactVersionSelector
          currentVersionId={artifactQuery.data.current_version_id}
          onValueChange={setVersionId}
          value={versionId}
          versions={artifactQuery.data.versions}
        />
      ) : null}
      <ArtifactPreviewFrame
        artifactType={artifactQuery.data.artifact_type}
        content={contentQuery.data}
        title={`${title} preview`}
        versionId={versionId}
      />
    </div>
  )
}

function ArtifactFailureRow({ activity, state }: { activity: ToolActivity; state: ArtifactState }) {
  const message =
    typeof activity.result === "string" && activity.result.trim()
      ? activity.result
      : activity.status === "denied"
        ? state.kind === "change"
          ? "This artifact change was declined. Nothing was saved."
          : "This artifact lookup was declined. Nothing was read."
        : state.kind === "change"
          ? "The artifact change did not finish. No result was confirmed."
          : "The artifact lookup did not finish. No result was confirmed."
  return (
    <ToolResultCard
      ariaLabel={`${state.heading} failed`}
      defaultOpen
      details={[{ label: "Action", value: state.heading }]}
      heading={<ArtifactHeading icon={state.icon}>{state.heading}</ArtifactHeading>}
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

type ArtifactState = {
  heading: string
  icon: LucideIcon
  kind: "change" | "lookup"
  pastTense: string
  runningLabel: string
  waitingLabel: string
}

function artifactState(toolName: string): ArtifactState | null {
  if (toolName === CREATE_ARTIFACT_TOOL_NAME) {
    return {
      heading: "Create Artifact",
      icon: FileCode2Icon,
      kind: "change",
      pastTense: "Created",
      runningLabel: "Creating artifact…",
      waitingLabel: "Waiting to create artifact…",
    }
  }
  if (toolName === LIST_ARTIFACTS_TOOL_NAME) {
    return {
      heading: "List Artifacts",
      icon: FilesIcon,
      kind: "lookup",
      pastTense: "Listed",
      runningLabel: "Finding artifacts…",
      waitingLabel: "Waiting to list artifacts…",
    }
  }
  if (toolName === READ_ARTIFACT_TOOL_NAME) {
    return {
      heading: "Read Artifact",
      icon: FileTextIcon,
      kind: "lookup",
      pastTense: "Read",
      runningLabel: "Reading artifact…",
      waitingLabel: "Waiting to read artifact…",
    }
  }
  if (toolName === UPDATE_ARTIFACT_TOOL_NAME) {
    return {
      heading: "Update Artifact",
      icon: RefreshCwIcon,
      kind: "change",
      pastTense: "Updated",
      runningLabel: "Updating artifact…",
      waitingLabel: "Waiting to update artifact…",
    }
  }
  return null
}

function artifactPendingSummary(activity: ToolActivity) {
  if (activity.name === LIST_ARTIFACTS_TOOL_NAME) {
    return artifactSearchArg(activity.args)
  }
  if (activity.name === READ_ARTIFACT_TOOL_NAME) {
    return artifactReferenceArg(activity.args)?.label ?? null
  }
  return artifactTitleArg(activity.args)
}

function ArtifactEntityLink({ artifactId, title }: { artifactId: string; title: string }) {
  return (
    <a
      className="block min-w-0 truncate text-sm font-medium hover:underline"
      href={`/artifacts/${encodeURIComponent(artifactId)}`}
    >
      {title}
    </a>
  )
}

function ArtifactHeading({ children, icon: Icon }: { children: string; icon: LucideIcon }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <Icon className="text-muted-foreground size-4 shrink-0" />
      <span className="truncate">{children}</span>
    </span>
  )
}

function ArtifactTypeIcon({ type }: { type: ArtifactType }) {
  if (type === "html") {
    return <FileCode2Icon className="size-4" />
  }
  if (type === "csv") {
    return <Table2Icon className="size-4" />
  }
  if (type === "mermaid") {
    return <WorkflowIcon className="size-4" />
  }
  if (type === "image-ref") {
    return <ImageIcon className="size-4" />
  }
  return <FileTextIcon className="size-4" />
}
