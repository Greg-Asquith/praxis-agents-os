// apps/web/src/features/conversations/components/code-mode-presenter.tsx

import { CodeModeRow } from "@/features/conversations/components/code-mode-row"
import type { ToolRowPresenter } from "@/integrations/contract"

const RUN_WORKFLOW_TOOL_NAME = "run_workflow"

export const codeModeWorkflowPresenter: ToolRowPresenter = {
  handlesApprovals: true,
  key: "code-mode-workflow",
  matches: (activity) => activity.name === RUN_WORKFLOW_TOOL_NAME && Boolean(activity.script),
  render: ({ activity, defaultOpen, live }) => (
    <CodeModeRow activity={activity} defaultOpen={defaultOpen} live={live} />
  ),
}
