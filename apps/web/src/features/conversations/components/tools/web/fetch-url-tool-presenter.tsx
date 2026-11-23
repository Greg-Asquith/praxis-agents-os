// apps/web/src/features/conversations/components/tools/web/fetch-url-tool-presenter.tsx

import {
  FETCH_URL_TOOL_NAME,
  fetchUrlArgsUrl,
  fetchUrlResult,
} from "@/features/conversations/components/tools/web/fetch-url-result"
import { FetchUrlToolRow } from "@/features/conversations/components/tools/web/fetch-url-tool-row"
import type { ToolRowPresenter } from "@/integrations/contract"

export const fetchUrlToolPresenter: ToolRowPresenter = {
  key: "fetch-url",
  matches: (activity) =>
    activity.name === FETCH_URL_TOOL_NAME &&
    (activity.status === "running"
      ? fetchUrlArgsUrl(activity.args) !== null
      : activity.status === "completed" && fetchUrlResult(activity.result) !== null),
  render: ({ activity, defaultOpen }) => (
    <FetchUrlToolRow activity={activity} defaultOpen={defaultOpen} />
  ),
}
