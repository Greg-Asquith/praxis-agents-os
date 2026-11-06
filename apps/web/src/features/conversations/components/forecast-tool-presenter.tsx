// apps/web/src/features/conversations/components/forecast-tool-presenter.tsx

import { ForecastToolRow } from "@/features/conversations/components/forecast-tool-row"
import {
  FORECAST_SERIES_TOOL_NAME,
  forecastToolResult,
} from "@/features/conversations/native-tools/forecast-tool"
import type { ToolRowPresenter } from "@/integrations/contract"

// Failed calls keep the default row, which shows the reason.
export const forecastToolPresenter: ToolRowPresenter = {
  key: "forecast-series",
  matches: (activity) =>
    activity.name === FORECAST_SERIES_TOOL_NAME &&
    (activity.status === "running" ||
      (activity.status === "completed" && forecastToolResult(activity.result) !== null)),
  render: ({ activity }) => <ForecastToolRow activity={activity} />,
}
