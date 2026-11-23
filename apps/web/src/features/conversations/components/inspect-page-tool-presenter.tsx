// apps/web/src/features/conversations/components/inspect-page-tool-presenter.tsx

import { parseResultPreview } from "@/components/tool-ui/result-preview"
import {
  INSPECT_PAGE_TOOL_NAME,
  inspectPageArgsUrl,
  inspectPageResult,
} from "@/features/conversations/components/inspect-page-result"
import { InspectPageToolRow } from "@/features/conversations/components/inspect-page-tool-row"
import type { ToolRowPresenter } from "@/integrations/contract"

export const inspectPageToolPresenter: ToolRowPresenter = {
  key: "inspect-page",
  matches: (activity) =>
    activity.name === INSPECT_PAGE_TOOL_NAME &&
    (activity.status === "running"
      ? inspectPageArgsUrl(activity.args) !== null
      : activity.status === "completed" &&
        inspectPageResult(parseResultPreview(activity.result)?.data ?? activity.result) !== null),
  render: ({ activity, defaultOpen }) => (
    <InspectPageToolRow activity={activity} defaultOpen={defaultOpen} />
  ),
}
