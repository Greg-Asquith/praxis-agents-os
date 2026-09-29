// apps/web/src/features/conversations/components/skill-tool-row.tsx

import { useState, type ReactNode } from "react"
import { Link } from "@tanstack/react-router"
import { FileTextIcon, SparklesIcon } from "lucide-react"

import { MarkdownContent } from "@/components/markdown/markdown-content"
import { DeclinedResult } from "@/components/tool-ui/declined-result"
import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ActivityStatusBadge } from "@/features/conversations/components/tool-activity-status"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  CREATE_SKILL_TOOL_NAME,
  SEARCH_SKILLS_TOOL_NAME,
  type LoadSkillToolResult,
  type SkillToolSummary,
  loadSkillResult,
  savedSkillResult,
  searchSkillsQueryArg,
  searchSkillsResult,
  skillToolLabel,
} from "@/features/conversations/native-tools/skill-tools"
import {
  loadedSkillNameFromArgs,
  skillActivationDisplayName,
} from "@/features/conversations/skills/skill-activation"
import { pluralize } from "@/lib/format"

type SkillToolRowProps = {
  activity: ToolActivity
  defaultOpen: boolean
}

const VISIBLE_SKILL_LIMIT = 5

export function SkillToolRow({ activity, defaultOpen }: SkillToolRowProps) {
  const isSearch = activity.name === SEARCH_SKILLS_TOOL_NAME
  if (activity.status === "running" || activity.status === "awaiting_approval") {
    return <SkillPendingRow activity={activity} />
  }
  if (
    activity.status === "failed" ||
    activity.status === "denied" ||
    activity.status === "unknown"
  ) {
    return <SkillFailureRow activity={activity} />
  }
  if (isSearch) {
    return <SearchSkillsRow activity={activity} defaultOpen={defaultOpen} />
  }
  const loaded = loadSkillResult(activity.result)
  if (loaded) {
    return <LoadSkillRow activity={activity} defaultOpen={defaultOpen} skill={loaded} />
  }
  const saved = savedSkillResult(activity.result)
  return saved ? (
    <SavedSkillRow activity={activity} defaultOpen={defaultOpen} skill={saved} />
  ) : null
}

function SearchSkillsRow({ activity, defaultOpen }: SkillToolRowProps) {
  const [showAll, setShowAll] = useState(false)
  const result = searchSkillsResult(activity.result)
  if (!result) {
    return null
  }
  const query = searchSkillsQueryArg(activity.args)
  const visible = showAll ? result.skills : result.skills.slice(0, VISIBLE_SKILL_LIMIT)
  const hiddenCount = result.skills.length - visible.length
  return (
    <ToolResultCard
      ariaLabel={query ? `Skill search results for ${query}` : "All skills"}
      defaultOpen={defaultOpen}
      details={[
        { label: "Search", value: query ?? "All skills" },
        { label: "Found", value: String(result.total) },
      ]}
      heading={<SkillHeading>Search Skills</SkillHeading>}
      trailing={
        <Badge variant={result.total > 0 ? "success" : "outline"}>
          {`${String(result.total)} ${pluralize(result.total, "Skill")}`}
        </Badge>
      }
    >
      <div className="grid min-w-0 gap-2">
        {visible.length > 0 ? (
          <ol aria-label="Skills found" className="divide-border divide-y rounded-lg border">
            {visible.map((skill) => (
              <li className="flex min-w-0 flex-col gap-1 px-3 py-2" key={skill.name}>
                <SkillIdentity skill={skill} />
                <p className="text-muted-foreground line-clamp-2 text-sm">{skill.description}</p>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-muted-foreground px-4 py-6 text-center text-sm">
            No matching skills were found.
          </p>
        )}
        {hiddenCount > 0 || showAll ? (
          <Button
            className="justify-self-start"
            onClick={() => {
              setShowAll((current) => !current)
            }}
            size="sm"
            type="button"
            variant="ghost"
          >
            {showAll ? "Show Fewer" : `Show All ${String(result.skills.length)} Skills`}
          </Button>
        ) : null}
      </div>
    </ToolResultCard>
  )
}

function LoadSkillRow({
  activity,
  defaultOpen,
  skill,
}: SkillToolRowProps & { skill: LoadSkillToolResult }) {
  const label = skillToolLabel(skill)
  return (
    <ToolResultCard
      ariaLabel={`Activated skill: ${label}`}
      defaultOpen={defaultOpen}
      details={[
        { label: "Skill", value: label },
        ...(skill.documents.length > 0
          ? [{ label: "Documents", value: String(skill.documents.length) }]
          : []),
      ]}
      heading={<SkillHeading>{`Activated Skill: ${label}`}</SkillHeading>}
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      <div className="grid min-w-0 gap-3">
        <SkillIdentity skill={skill} />
        <div className="border-border overflow-hidden rounded-lg border">
          <p className="bg-muted/25 border-b px-3 py-2 text-xs font-medium">Instructions</p>
          <div className="max-h-96 min-w-0 overflow-auto px-3 py-2">
            <MarkdownContent content={skill.instructions} />
          </div>
        </div>
        {skill.documents.length > 0 ? (
          <ul aria-label="Skill documents" className="grid gap-1">
            {skill.documents.map((document) => (
              <li
                className="text-muted-foreground flex min-w-0 items-center gap-2 text-sm"
                key={document.name}
              >
                <FileTextIcon className="size-4 shrink-0" />
                <span className="truncate">{document.filename}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </ToolResultCard>
  )
}

function SavedSkillRow({
  activity,
  defaultOpen,
  skill,
}: SkillToolRowProps & { skill: SkillToolSummary }) {
  const verb = activity.name === CREATE_SKILL_TOOL_NAME ? "Created" : "Updated"
  const label = skillToolLabel(skill)
  return (
    <ToolResultCard
      ariaLabel={`${verb} skill: ${label}`}
      defaultOpen={defaultOpen}
      details={[{ label: "Skill", value: label }]}
      heading={<SkillHeading>{`${verb} Skill: ${label}`}</SkillHeading>}
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      <div className="grid min-w-0 gap-2">
        <SkillIdentity skill={skill} />
        <p className="text-muted-foreground text-sm">{skill.description}</p>
        <p className="text-muted-foreground text-xs">
          {skill.scope === "platform"
            ? "Agents in every workspace can use this skill."
            : "Agents in this workspace can use this skill."}
        </p>
      </div>
    </ToolResultCard>
  )
}

function SkillIdentity({ skill }: { skill: SkillToolSummary }) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      {skill.id ? (
        <Link
          className="min-w-0 truncate text-sm font-medium hover:underline"
          params={{ skillId: skill.id }}
          to="/skills/$skillId"
        >
          {skillToolLabel(skill)}
        </Link>
      ) : (
        <span className="min-w-0 truncate text-sm font-medium">{skillToolLabel(skill)}</span>
      )}
      {skill.scope === "platform" ? <Badge variant="secondary">Platform</Badge> : null}
      {skill.scope === "platform" && skill.owner ? (
        <span className="text-muted-foreground text-xs">Owned by {skill.owner}</span>
      ) : null}
    </div>
  )
}

function SkillPendingRow({ activity }: Pick<SkillToolRowProps, "activity">) {
  const state = skillPendingState(activity)
  return (
    <FanOutSkeleton
      heading={<SkillHeading>{state.heading}</SkillHeading>}
      label={activity.status === "running" ? state.runningLabel : state.waitingLabel}
      {...(state.summary ? { summary: state.summary } : {})}
    />
  )
}

function SkillFailureRow({ activity }: Pick<SkillToolRowProps, "activity">) {
  const state = skillPendingState(activity)
  const failureMessage =
    typeof activity.result === "string" && activity.result.trim()
      ? activity.result
      : "The skill lookup did not finish. No result was confirmed."
  return (
    <ToolResultCard
      ariaLabel={`${state.heading} ${activity.status === "denied" ? "declined" : "failed"}`}
      defaultOpen
      details={[{ label: "Action", value: state.heading }]}
      heading={<SkillHeading>{state.heading}</SkillHeading>}
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      {activity.status === "denied" ? (
        <DeclinedResult
          description="This skill lookup was declined. Nothing was read."
          reason={activity.decisionReason}
        />
      ) : (
        <Alert variant="destructive">
          <AlertTitle>What Went Wrong</AlertTitle>
          <AlertDescription className="whitespace-pre-wrap">{failureMessage}</AlertDescription>
        </Alert>
      )}
    </ToolResultCard>
  )
}

function skillPendingState(activity: ToolActivity) {
  if (activity.name === SEARCH_SKILLS_TOOL_NAME) {
    const query = searchSkillsQueryArg(activity.args)
    return {
      heading: "Search Skills",
      runningLabel: query ? `Searching skills for ${query}…` : "Listing skills…",
      summary: query,
      waitingLabel: "Waiting to search skills…",
    }
  }
  const name = loadedSkillNameFromArgs(activity.args)
  const label = name ? skillActivationDisplayName(null, name) : null
  return {
    heading: label ? `Activate Skill: ${label}` : "Activate Skill",
    runningLabel: "Loading skill instructions…",
    summary: label,
    waitingLabel: "Waiting to load skill…",
  }
}

function SkillHeading({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <SparklesIcon className="text-muted-foreground size-4 shrink-0" />
      <span className="truncate">{children}</span>
    </span>
  )
}
