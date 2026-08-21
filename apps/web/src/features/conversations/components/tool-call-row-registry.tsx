// apps/web/src/features/conversations/components/tool-call-row-registry.tsx

import { artifactToolPresenter } from "@/features/conversations/components/artifact-tool-presenter"
import { chartToolPresenter } from "@/features/conversations/components/chart-tool-presenter"
import { classifierToolPresenter } from "@/features/conversations/components/classifier-tool-presenter"
import { codeModeWorkflowPresenter } from "@/features/conversations/components/code-mode-presenter"
import { completionReportPresenter } from "@/features/conversations/components/completion-report-presenter"
import { delegationToolPresenters } from "@/features/conversations/components/delegation-tool-presenter"
import { fileToolPresenter } from "@/features/conversations/components/file-tool-presenter"
import { kbToolPresenter } from "@/features/conversations/components/kb-tool-presenter"
import { memoryToolPresenter } from "@/features/conversations/components/memory-tool-presenter"
import { runCodeToolPresenter } from "@/features/conversations/components/run-code-tool-presenter"
import { skillActivationPresenter } from "@/features/conversations/components/skill-activation-presenter"
import { skillDocumentReadPresenter } from "@/features/conversations/components/skill-document-read-presenter"
import { todoToolPresenters } from "@/features/conversations/components/todo-list-presenter"
import { webFetchToolPresenter } from "@/features/conversations/components/web-fetch-tool-presenter"
import { webSearchToolPresenter } from "@/features/conversations/components/web-search-tool-presenter"
import type { ToolRowPresenter, ToolRowPresenterProps } from "@/integrations/contract"
import { integrationToolRowPresenters } from "@/integrations/registry"

// Tool rows resolve in three layers: a custom presenter registered here wins,
// otherwise the default row renders from the tool's server-declared presentation
// (/tools/presentations), otherwise from generic verb + label fallbacks.
// Register a presenter only when a tool needs richer UI than the declarative
// config can express; everything else should be configured on its backend
// runtime_tool definition.

export const TOOL_ROW_PRESENTERS: ToolRowPresenter[] = [
  runCodeToolPresenter,
  codeModeWorkflowPresenter,
  completionReportPresenter,
  artifactToolPresenter,
  classifierToolPresenter,
  chartToolPresenter,
  webFetchToolPresenter,
  webSearchToolPresenter,
  ...delegationToolPresenters,
  skillActivationPresenter,
  skillDocumentReadPresenter,
  ...todoToolPresenters,
  fileToolPresenter,
  kbToolPresenter,
  memoryToolPresenter,
]

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
