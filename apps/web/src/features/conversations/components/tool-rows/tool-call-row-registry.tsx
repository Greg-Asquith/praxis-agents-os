// apps/web/src/features/conversations/components/tool-rows/tool-call-row-registry.tsx

import { artifactToolPresenter } from "@/features/conversations/components/tools/files/artifact-tool-presenter"
import { askUrlToolPresenter } from "@/features/conversations/components/tools/web/ask-url-tool-presenter"
import { checkUrlsToolPresenter } from "@/features/conversations/components/tools/web/check-urls-tool-presenter"
import { chartToolPresenter } from "@/features/conversations/components/tools/analysis/chart-tool-presenter"
import { classifierToolPresenter } from "@/features/conversations/components/tools/analysis/classifier-tool-presenter"
import { codeModeWorkflowPresenter } from "@/features/conversations/components/tools/code-mode/code-mode-presenter"
import { completionReportPresenter } from "@/features/conversations/components/tools/runtime/completion-report-presenter"
import { documentToolPresenter } from "@/features/conversations/components/tools/files/document-tool-presenter"
import { delegationToolPresenters } from "@/features/conversations/components/tools/delegation/delegation-tool-presenter"
import { forecastToolPresenter } from "@/features/conversations/components/tools/analysis/forecast-tool-presenter"
import { fetchUrlToolPresenter } from "@/features/conversations/components/tools/web/fetch-url-tool-presenter"
import { inspectPageToolPresenter } from "@/features/conversations/components/tools/web/inspect-page-tool-presenter"
import { pageSpeedToolPresenter } from "@/features/conversations/components/tools/web/page-speed-tool-presenter"
import { fileToolPresenter } from "@/features/conversations/components/tools/files/file-tool-presenter"
import { kbToolPresenter } from "@/features/conversations/components/tools/knowledge/kb-tool-presenter"
import { memoryToolPresenter } from "@/features/conversations/components/tools/knowledge/memory-tool-presenter"
import { skillActivationPresenter } from "@/features/conversations/components/tools/skills/skill-activation-presenter"
import { skillDocumentReadPresenter } from "@/features/conversations/components/tools/skills/skill-document-read-presenter"
import { skillToolPresenter } from "@/features/conversations/components/tools/skills/skill-tool-presenter"
import { todoToolPresenters } from "@/features/conversations/components/tools/runtime/todo-list-presenter"
import { toolSearchPresenter } from "@/features/conversations/components/tools/runtime/tool-search-presenter"
import {
  videoResultPresenter,
  videoToolPresenters,
} from "@/features/conversations/components/tools/video/video-tool-presenter"
import { webSearchToolPresenter } from "@/features/conversations/components/tools/web/web-search-tool-presenter"
import type { ToolRowPresenter, ToolRowPresenterProps } from "@/integrations/contract"
import { integrationToolRowPresenters } from "@/integrations/registry"

// Tool rows resolve in three layers: a custom presenter registered here wins,
// otherwise the default row renders from the tool's server-declared presentation
// (/tools/presentations), otherwise from generic verb + label fallbacks.
// Register a presenter only when a tool needs richer UI than the declarative
// config can express; everything else should be configured on its backend
// runtime_tool definition.

const TOOL_ROW_PRESENTERS: ToolRowPresenter[] = [
  codeModeWorkflowPresenter,
  completionReportPresenter,
  artifactToolPresenter,
  classifierToolPresenter,
  chartToolPresenter,
  forecastToolPresenter,
  askUrlToolPresenter,
  fetchUrlToolPresenter,
  checkUrlsToolPresenter,
  inspectPageToolPresenter,
  pageSpeedToolPresenter,
  webSearchToolPresenter,
  ...delegationToolPresenters,
  skillActivationPresenter,
  skillDocumentReadPresenter,
  skillToolPresenter,
  toolSearchPresenter,
  ...todoToolPresenters,
  fileToolPresenter,
  documentToolPresenter,
  kbToolPresenter,
  memoryToolPresenter,
  ...videoToolPresenters,
]

export function renderCustomToolCallRow(props: ToolRowPresenterProps) {
  if (props.activity.status === "stopped") return null
  for (const presenter of [
    ...TOOL_ROW_PRESENTERS,
    ...integrationToolRowPresenters(props.providerKey),
    videoResultPresenter,
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
