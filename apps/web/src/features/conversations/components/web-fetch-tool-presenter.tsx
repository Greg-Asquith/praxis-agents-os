// apps/web/src/features/conversations/components/web-fetch-tool-presenter.tsx

import {
  WEB_FETCH_TOOL_NAME,
  webFetchResult,
  webFetchUrl,
} from "@/features/conversations/components/web-fetch-result"
import { WebFetchToolRow } from "@/features/conversations/components/web-fetch-tool-row"
import type { ToolRowPresenter } from "@/integrations/contract"

export const webFetchToolPresenter: ToolRowPresenter = {
  key: "web-fetch",
  matches: (activity) =>
    activity.name === WEB_FETCH_TOOL_NAME &&
    (activity.status === "running"
      ? webFetchUrl(activity.args) !== null
      : activity.status === "completed" && webFetchResult(activity.result) !== null),
  render: ({ activity, defaultOpen }) => (
    <WebFetchToolRow activity={activity} defaultOpen={defaultOpen} />
  ),
}
