// apps/web/src/features/conversations/components/chart-tool-presenter.tsx

import { ChartToolRow } from "@/features/conversations/components/chart-tool-row"
import { BUILD_CHART_TOOL_NAME } from "@/features/conversations/native-tools/chart-tool"
import type { ToolRowPresenter } from "@/integrations/contract"

export const chartToolPresenter: ToolRowPresenter = {
  key: "build-chart",
  matches: (activity) =>
    activity.name === BUILD_CHART_TOOL_NAME &&
    (activity.status === "running" || activity.status === "completed"),
  render: ({ activity }) => <ChartToolRow activity={activity} />,
}
