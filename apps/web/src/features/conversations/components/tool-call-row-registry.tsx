// apps/web/src/features/conversations/components/tool-call-row-registry.tsx

import {
  DelegateAgentListRow,
  DelegationToolRow,
} from "@/features/conversations/components/delegation-tool-row"
import { ArtifactToolRow } from "@/features/conversations/components/artifact-tool-row"
import { ChartToolRow } from "@/features/conversations/components/chart-tool-row"
import { CompletionReportRow } from "@/features/conversations/components/completion-report-row"
import { FileToolRow } from "@/features/conversations/components/file-tool-row"
import { KbToolRow } from "@/features/conversations/components/kb-tool-row"
import { MemoryToolRow } from "@/features/conversations/components/memory-tool-row"
import { SkillActivationRow } from "@/features/conversations/components/skill-activation-row"
import { SkillDocumentReadRow } from "@/features/conversations/components/skill-document-read-row"
import { TodoListRow } from "@/features/conversations/components/todo-list-row"
import { webFetchResult, webFetchUrl } from "@/features/conversations/components/web-fetch-result"
import { WebFetchToolRow } from "@/features/conversations/components/web-fetch-tool-row"
import {
  webSearchQuery,
  webSearchResult,
} from "@/features/conversations/components/web-search-result"
import { WebSearchToolRow } from "@/features/conversations/components/web-search-tool-row"
import {
  LIST_FILES_TOOL_NAME,
  READ_FILE_TOOL_NAME,
  WRITE_FILE_TOOL_NAME,
  listFilesResult,
  readFileContentResult,
  readFileImageResult,
  readFileStatusResult,
  readFileUrlResult,
  writeFileResult,
} from "@/features/conversations/native-tools/file-tools"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  LIST_DELEGATE_AGENTS_TOOL_NAME,
  delegateAgentSummaries,
} from "@/features/conversations/delegation-agent-list"
import {
  LOAD_CAPABILITY_TOOL_NAME,
  skillIdFromCapabilityArgs,
} from "@/features/conversations/skills/skill-activation"
import { BUILD_CHART_TOOL_NAME } from "@/features/conversations/native-tools/chart-tool"
import {
  REPORT_COMPLETION_TOOL_NAME,
  completionReport,
} from "@/features/conversations/native-tools/completion-tool"
import { READ_SKILL_DOCUMENT_TOOL_NAME } from "@/features/conversations/skills/skill-document-read"
import {
  READ_DOCUMENT_TOOL_NAME,
  SEARCH_KNOWLEDGE_TOOL_NAME,
  readDocumentResult,
  searchKnowledgeResult,
} from "@/features/conversations/native-tools/kb-tools"
import {
  FORGET_MEMORY_TOOL_NAME,
  SAVE_MEMORY_TOOL_NAME,
  SEARCH_MEMORY_TOOL_NAME,
  UPDATE_MEMORY_TOOL_NAME,
  forgetMemoryResult,
  saveMemoryResult,
  searchMemoryResult,
  updateMemoryResult,
} from "@/features/conversations/native-tools/memory-tools"
import {
  READ_TODOS_TOOL_NAME,
  WRITE_TODOS_TOOL_NAME,
  todoItemsFromActivity,
} from "@/features/conversations/native-tools/todo-tools"
import {
  CREATE_ARTIFACT_TOOL_NAME,
  UPDATE_ARTIFACT_TOOL_NAME,
  artifactToolResult,
} from "@/features/conversations/native-tools/artifact-tools"
import { integrationToolRowPresenters } from "@/integrations/registry"
import type { ToolRowPresenter, ToolRowPresenterProps } from "@/integrations/contract"

// Tool rows resolve in three layers: a custom presenter registered here wins,
// otherwise the default row renders from the tool's server-declared presentation
// (/tools/presentations), otherwise from generic verb + label fallbacks.
// Register a presenter only when a tool needs richer UI than the declarative
// config can express; everything else should be configured on its backend
// runtime_tool definition.

const TOOL_ROW_PRESENTERS: ToolRowPresenter[] = [
  {
    key: "completion-report",
    matches: (activity) =>
      activity.name === REPORT_COMPLETION_TOOL_NAME &&
      (activity.status === "running" ||
        (activity.status === "completed" && completionReport(activity.result) !== null)),
    render: ({ activity, defaultOpen }) => (
      <CompletionReportRow activity={activity} defaultOpen={defaultOpen} />
    ),
  },
  {
    key: "artifact-tools",
    matches: artifactToolRowMatches,
    render: ({ activity, defaultOpen }) => (
      <ArtifactToolRow activity={activity} defaultOpen={defaultOpen} />
    ),
  },
  {
    key: "build-chart",
    matches: (activity) =>
      activity.name === BUILD_CHART_TOOL_NAME &&
      (activity.status === "running" || activity.status === "completed"),
    render: ({ activity }) => <ChartToolRow activity={activity} />,
  },
  {
    key: "web-fetch",
    matches: (activity) =>
      activity.name === "fetch_url" &&
      (activity.status === "running"
        ? webFetchUrl(activity.args) !== null
        : activity.status === "completed" && webFetchResult(activity.result) !== null),
    render: ({ activity, defaultOpen }) => (
      <WebFetchToolRow activity={activity} defaultOpen={defaultOpen} />
    ),
  },
  {
    key: "web-search",
    matches: (activity) =>
      activity.name === "web_search" &&
      (activity.status === "running"
        ? webSearchQuery(activity.args) !== null
        : activity.status === "completed" && webSearchResult(activity.result) !== null),
    render: ({ activity, defaultOpen }) => (
      <WebSearchToolRow activity={activity} defaultOpen={defaultOpen} />
    ),
  },
  {
    key: "delegate-agent-list",
    matches: (activity) =>
      activity.name === LIST_DELEGATE_AGENTS_TOOL_NAME &&
      (activity.status === "running" || delegateAgentSummaries(activity.result) !== null),
    render: ({ activity, defaultOpen }) => (
      <DelegateAgentListRow activity={activity} defaultOpen={defaultOpen} />
    ),
  },
  {
    handlesApprovals: true,
    key: "delegation",
    matches: (activity) => Boolean(activity.delegate),
    render: ({ activity, approvalDecision, defaultOpen }) => (
      <DelegationToolRow
        activity={activity}
        {...(approvalDecision ? { approvalDecision } : {})}
        defaultOpen={defaultOpen}
      />
    ),
  },
  {
    key: "skill-activation",
    matches: (activity) =>
      (activity.toolKind === "capability-load" || activity.name === LOAD_CAPABILITY_TOOL_NAME) &&
      skillIdFromCapabilityArgs(activity.args) !== null,
    render: ({ activity }) => <SkillActivationRow activity={activity} />,
  },
  {
    key: "skill-document-read",
    matches: (activity) => activity.name === READ_SKILL_DOCUMENT_TOOL_NAME,
    render: ({ activity, defaultOpen }) => (
      <SkillDocumentReadRow activity={activity} defaultOpen={defaultOpen} />
    ),
  },
  {
    key: "todo-plan",
    matches: (activity) =>
      activity.name === WRITE_TODOS_TOOL_NAME && todoItemsFromActivity(activity) !== null,
    render: ({ activity }) => <TodoListRow activity={activity} />,
  },
  {
    key: "todo-lookup",
    matches: (activity) =>
      activity.name === READ_TODOS_TOOL_NAME &&
      (activity.status !== "completed" || todoItemsFromActivity(activity) !== null),
    render: ({ activity }) => <TodoListRow activity={activity} />,
  },
  {
    handlesApprovals: true,
    key: "file-tools",
    matches: fileToolRowMatches,
    render: ({ activity, approvalDecision, defaultOpen, label, ui }) => (
      <FileToolRow
        activity={activity}
        {...(approvalDecision ? { approvalDecision } : {})}
        defaultOpen={defaultOpen}
        label={label ?? activity.name}
        ui={ui ?? null}
      />
    ),
  },
  {
    key: "kb-tools",
    matches: kbToolRowMatches,
    render: ({ activity, defaultOpen }) => (
      <KbToolRow activity={activity} defaultOpen={defaultOpen} />
    ),
  },
  {
    handlesApprovals: true,
    key: "memory-tools",
    matches: memoryToolRowMatches,
    render: ({ activity, approvalDecision, defaultOpen, label, ui }) => (
      <MemoryToolRow
        activity={activity}
        {...(approvalDecision ? { approvalDecision } : {})}
        defaultOpen={defaultOpen}
        label={label ?? activity.name}
        ui={ui ?? null}
      />
    ),
  },
]

function artifactToolRowMatches(activity: ToolActivity) {
  if (
    (activity.name === CREATE_ARTIFACT_TOOL_NAME || activity.name === UPDATE_ARTIFACT_TOOL_NAME) &&
    activity.status !== "completed"
  ) {
    return true
  }
  return (
    (activity.name === CREATE_ARTIFACT_TOOL_NAME || activity.name === UPDATE_ARTIFACT_TOOL_NAME) &&
    artifactToolResult(activity.result) !== null
  )
}

export function renderCustomToolCallRow(props: ToolRowPresenterProps) {
  for (const presenter of [
    ...TOOL_ROW_PRESENTERS,
    ...integrationToolRowPresenters(props.providerKey),
  ]) {
    try {
      if (
        (props.approvalDecision === undefined || presenter.handlesApprovals === true) &&
        presenter.matches(props.activity)
      ) {
        return presenter.render(props)
      }
    } catch (error) {
      console.error(
        `Tool row presenter '${presenter.key}' failed for tool '${props.activity.name}'.`,
        error
      )
    }
  }
  return null
}

function kbToolRowMatches(activity: ToolActivity) {
  if (
    (activity.name === SEARCH_KNOWLEDGE_TOOL_NAME || activity.name === READ_DOCUMENT_TOOL_NAME) &&
    activity.status !== "completed"
  ) {
    return true
  }
  if (activity.name === SEARCH_KNOWLEDGE_TOOL_NAME) {
    return searchKnowledgeResult(activity.result) !== null
  }
  if (activity.name === READ_DOCUMENT_TOOL_NAME) {
    return readDocumentResult(activity.result) !== null
  }
  return false
}

function memoryToolRowMatches(activity: ToolActivity) {
  if (
    (activity.name === SAVE_MEMORY_TOOL_NAME ||
      activity.name === SEARCH_MEMORY_TOOL_NAME ||
      activity.name === UPDATE_MEMORY_TOOL_NAME ||
      activity.name === FORGET_MEMORY_TOOL_NAME) &&
    activity.status !== "completed"
  ) {
    return true
  }
  if (activity.name === SAVE_MEMORY_TOOL_NAME) {
    return saveMemoryResult(activity.result) !== null
  }
  if (activity.name === SEARCH_MEMORY_TOOL_NAME) {
    return searchMemoryResult(activity.result) !== null
  }
  if (activity.name === UPDATE_MEMORY_TOOL_NAME) {
    return updateMemoryResult(activity.result) !== null
  }
  if (activity.name === FORGET_MEMORY_TOOL_NAME) {
    return forgetMemoryResult(activity.result) !== null
  }
  return false
}

function fileToolRowMatches(activity: ToolActivity) {
  if (
    (activity.name === LIST_FILES_TOOL_NAME ||
      activity.name === WRITE_FILE_TOOL_NAME ||
      activity.name === READ_FILE_TOOL_NAME) &&
    activity.status !== "completed"
  ) {
    return true
  }
  if (activity.name === LIST_FILES_TOOL_NAME) {
    return listFilesResult(activity.result) !== null
  }
  if (activity.name === WRITE_FILE_TOOL_NAME) {
    return writeFileResult(activity.result) !== null
  }
  if (activity.name === READ_FILE_TOOL_NAME) {
    return (
      readFileUrlResult(activity.result) !== null ||
      readFileContentResult(activity.result) !== null ||
      readFileStatusResult(activity.result) !== null ||
      readFileImageResult(activity.result) !== null
    )
  }
  return false
}
