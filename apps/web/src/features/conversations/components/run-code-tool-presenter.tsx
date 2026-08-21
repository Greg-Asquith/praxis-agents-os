// apps/web/src/features/conversations/components/run-code-tool-presenter.tsx

import { RunCodeToolRow } from "@/features/conversations/components/run-code-tool-row"
import { RUN_CODE_TOOL_NAME, runCodeResult } from "@/features/conversations/native-tools/run-code"
import type { ToolRowPresenter } from "@/integrations/contract"

export const runCodeToolPresenter: ToolRowPresenter = {
  key: "run-code",
  matches: (activity) =>
    activity.name === RUN_CODE_TOOL_NAME &&
    (activity.status === "running" ||
      (activity.status === "completed" && runCodeResult(activity.result) !== null)),
  render: ({ activity, defaultOpen }) => (
    <RunCodeToolRow activity={activity} defaultOpen={defaultOpen} />
  ),
}
