// apps/web/src/features/conversations/components/web-search-tool-presenter.tsx

import {
  WEB_SEARCH_TOOL_NAME,
  webSearchQuery,
  webSearchResult,
} from "@/features/conversations/components/web-search-result"
import { WebSearchToolRow } from "@/features/conversations/components/web-search-tool-row"
import type { ToolRowPresenter } from "@/integrations/contract"

export const webSearchToolPresenter: ToolRowPresenter = {
  key: "web-search",
  matches: (activity) =>
    activity.name === WEB_SEARCH_TOOL_NAME &&
    (activity.status === "running"
      ? webSearchQuery(activity.args) !== null
      : activity.status === "completed" && webSearchResult(activity.result) !== null),
  render: ({ activity, defaultOpen }) => (
    <WebSearchToolRow activity={activity} defaultOpen={defaultOpen} />
  ),
}
