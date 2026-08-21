// apps/web/src/features/conversations/components/completion-report-presenter.tsx

import { CompletionReportRow } from "@/features/conversations/components/completion-report-row"
import {
  REPORT_COMPLETION_TOOL_NAME,
  completionReport,
} from "@/features/conversations/native-tools/completion-tool"
import type { ToolRowPresenter } from "@/integrations/contract"

export const completionReportPresenter: ToolRowPresenter = {
  key: "completion-report",
  matches: (activity) =>
    activity.name === REPORT_COMPLETION_TOOL_NAME &&
    (activity.status === "running" ||
      (activity.status === "completed" && completionReport(activity.result) !== null)),
  render: ({ activity, defaultOpen }) => (
    <CompletionReportRow activity={activity} defaultOpen={defaultOpen} />
  ),
}
