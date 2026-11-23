// apps/web/src/features/conversations/components/tools/web/page-speed-tool-presenter.tsx

import { parseResultPreview } from "@/components/tool-ui/result-preview"
import {
  MEASURE_PAGE_SPEED_TOOL_NAME,
  pageSpeedArgsCount,
  pageSpeedResult,
} from "@/features/conversations/components/tools/web/page-speed-result"
import { PageSpeedToolRow } from "@/features/conversations/components/tools/web/page-speed-tool-row"
import type { ToolRowPresenter } from "@/integrations/contract"

export const pageSpeedToolPresenter: ToolRowPresenter = {
  key: "measure-page-speed",
  matches: (activity) =>
    activity.name === MEASURE_PAGE_SPEED_TOOL_NAME &&
    (activity.status === "running"
      ? Boolean(pageSpeedArgsCount(activity.args))
      : activity.status === "completed" &&
        pageSpeedResult(parseResultPreview(activity.result)?.data ?? activity.result) !== null),
  render: ({ activity, defaultOpen }) => (
    <PageSpeedToolRow activity={activity} defaultOpen={defaultOpen} />
  ),
}
