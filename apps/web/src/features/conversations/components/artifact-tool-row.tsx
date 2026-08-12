// apps/web/src/features/conversations/components/artifact-tool-row.tsx

import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  ExternalLinkIcon,
  FileCode2Icon,
  FileTextIcon,
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
  UPDATE_ARTIFACT_TOOL_NAME,
  artifactTitleArg,
  artifactToolResult,
} from "@/features/conversations/native-tools/artifact-tools"
import { getErrorMessage } from "@/lib/api/errors"
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
    const title = artifactTitleArg(activity.args)
    return (
      <FanOutSkeleton
        heading={<ArtifactHeading icon={state.icon}>{state.heading}</ArtifactHeading>}
        label={activity.status === "running" ? state.runningLabel : state.waitingLabel}
        {...(title ? { summary: title } : {})}
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
        ? "This artifact change was declined. Nothing was saved."
        : "The artifact change did not finish. No result was confirmed."
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
  pastTense: string
  runningLabel: string
  waitingLabel: string
}

function artifactState(toolName: string): ArtifactState | null {
  if (toolName === CREATE_ARTIFACT_TOOL_NAME) {
    return {
      heading: "Create Artifact",
      icon: FileCode2Icon,
      pastTense: "Created",
      runningLabel: "Creating artifact…",
      waitingLabel: "Waiting to create artifact…",
    }
  }
  if (toolName === UPDATE_ARTIFACT_TOOL_NAME) {
    return {
      heading: "Update Artifact",
      icon: RefreshCwIcon,
      pastTense: "Updated",
      runningLabel: "Updating artifact…",
      waitingLabel: "Waiting to update artifact…",
    }
  }
  return null
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
  return <FileTextIcon className="size-4" />
}
