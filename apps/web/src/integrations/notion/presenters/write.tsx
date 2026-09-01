// apps/web/src/integrations/notion/presenters/write.tsx

import { ToolApprovalDecisionCard } from "@/components/tool-ui/approval-card"
import { approvalFallbackFields } from "@/components/tool-ui/approval-fallback-fields"
import type { FanOutEntry } from "@/components/tool-ui/fan-out"
import { FanOutShell } from "@/components/tool-ui/fan-out-shell"
import type { ToolActivity, ToolRowPresenter } from "@/integrations/contract"
import { NotionLogo } from "@/integrations/notion/components/logo"
import { NotionSkeleton } from "@/integrations/notion/components/read-results"
import { NotionWriteReceipt } from "@/integrations/notion/components/write-results"
import {
  parseNotionWriteFanOut,
  type NotionWriteKind,
} from "@/integrations/notion/lib/write-results"

type NotionWriteConfig = {
  approveLabel: string
  approvalPrompt: string
  approvalTitle: string
  kind: NotionWriteKind
  progressLabel: string
  title: string
  waitingLabel: string
}

const WRITE_CONFIGS: Record<string, NotionWriteConfig> = {
  notion_create_page: {
    approveLabel: "Approve & Create",
    approvalPrompt: "The agent wants to create this page in Notion.",
    approvalTitle: "Create Notion Page",
    kind: "create",
    progressLabel: "Creating Notion page…",
    title: "Create Notion Page",
    waitingLabel: "Waiting for page creation approval…",
  },
  notion_update_page_content: {
    approveLabel: "Approve & Update",
    approvalPrompt: "The agent wants to replace this text in Notion.",
    approvalTitle: "Update Notion Page Content",
    kind: "content",
    progressLabel: "Updating Notion page content…",
    title: "Update Notion Page Content",
    waitingLabel: "Waiting for page content approval…",
  },
  notion_update_page_properties: {
    approveLabel: "Approve & Update",
    approvalPrompt: "The agent wants to change these Notion page properties.",
    approvalTitle: "Update Notion Page Properties",
    kind: "properties",
    progressLabel: "Updating Notion page properties…",
    title: "Update Notion Page Properties",
    waitingLabel: "Waiting for page property approval…",
  },
}

export const notionWritePresenter: ToolRowPresenter = {
  handlesApprovals: true,
  key: "notion-writes",
  matches: (activity) => Object.hasOwn(WRITE_CONFIGS, activity.name),
  render: ({ activity, approvalDecision, defaultOpen, ui }) => {
    const config = WRITE_CONFIGS[activity.name]
    if (!config) {
      return null
    }
    if (approvalDecision) {
      const fields = ui?.arg_fields ?? []
      return (
        <ToolApprovalDecisionCard
          activityId={activity.id}
          approveLabel={ui?.approve_label ?? config.approveLabel}
          args={activity.args}
          controls={approvalDecision}
          fallbackFields={approvalFallbackFields(activity.args, fields)}
          fields={fields}
          icon={<NotionLogo className="size-4" />}
          label={config.title}
          prompt={ui?.approval_prompt ?? config.approvalPrompt}
          title={ui?.approval_title ?? config.approvalTitle}
          toolName={activity.name}
          {...(activity.derivedFromUntrusted === undefined
            ? {}
            : { derivedFromUntrusted: activity.derivedFromUntrusted })}
          {...(activity.taintSources === undefined ? {} : { taintSources: activity.taintSources })}
        />
      )
    }
    if (activity.status === "running" || activity.status === "awaiting_approval") {
      return (
        <NotionSkeleton
          label={
            activity.status === "awaiting_approval" ? config.waitingLabel : config.progressLabel
          }
          title={config.title}
        />
      )
    }
    if (
      activity.status === "denied" ||
      activity.status === "failed" ||
      activity.status === "unknown"
    ) {
      return writeFailure(
        activity,
        config,
        activity.status === "denied"
          ? "This Notion change was declined. Nothing was changed."
          : "The Notion change did not finish. No change was confirmed.",
        defaultOpen
      )
    }

    const fanOut = parseNotionWriteFanOut(
      activity.result,
      config.kind,
      "Praxis could not confirm the Notion change.",
      "Praxis couldn't verify whether Notion applied this change. Check the page in Notion before taking further action."
    )
    if (!fanOut) {
      return writeFailure(
        activity,
        config,
        "Praxis could not confirm the Notion change.",
        defaultOpen
      )
    }

    return (
      <div aria-label={`${config.title} results`} className="w-full min-w-0">
        <FanOutShell
          contextLabel="Workspace"
          defaultOpen={defaultOpen}
          entries={fanOut.entries}
          emptyLabel="No Notion workspaces received this change."
          externalLabel="Workspace ID"
          heading={notionHeading(config.title)}
        >
          {(_entry, index) => {
            const result = fanOut.data[index]
            return result ? <NotionWriteReceipt kind={config.kind} result={result} /> : null
          }}
        </FanOutShell>
      </div>
    )
  },
}

function writeFailure(
  activity: ToolActivity,
  config: NotionWriteConfig,
  description: string,
  defaultOpen: boolean
) {
  const entry: FanOutEntry = {
    data: null,
    displayName: "Selected Notion workspace",
    errorCode: null,
    errorMessage: description,
    externalId: "Selected Notion workspace",
    providerKey: "notion",
    renderKey: `notion:failure:${activity.id}`,
    status: "failed",
  }
  return (
    <div aria-label={`Unconfirmed ${config.title}`} className="w-full min-w-0">
      <FanOutShell
        contextLabel="Workspace"
        defaultOpen={defaultOpen}
        entries={[entry]}
        externalLabel="Workspace ID"
        heading={notionHeading(config.title)}
      >
        {() => null}
      </FanOutShell>
    </div>
  )
}

function notionHeading(title: string) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <NotionLogo aria-hidden="true" className="size-4 shrink-0" />
      <span className="truncate">{title}</span>
    </span>
  )
}
