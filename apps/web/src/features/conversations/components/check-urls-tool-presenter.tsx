// apps/web/src/features/conversations/components/check-urls-tool-presenter.tsx

import { parseResultPreview } from "@/components/tool-ui/result-preview"
import {
  CHECK_URLS_TOOL_NAME,
  checkUrlsArgsCount,
  checkUrlsResult,
} from "@/features/conversations/components/check-urls-result"
import { CheckUrlsToolRow } from "@/features/conversations/components/check-urls-tool-row"
import type { ToolRowPresenter } from "@/integrations/contract"

export const checkUrlsToolPresenter: ToolRowPresenter = {
  key: "check-urls",
  matches: (activity) =>
    activity.name === CHECK_URLS_TOOL_NAME &&
    (activity.status === "running"
      ? Boolean(checkUrlsArgsCount(activity.args))
      : activity.status === "completed" &&
        checkUrlsResult(parseResultPreview(activity.result)?.data ?? activity.result) !== null),
  render: ({ activity, defaultOpen }) => (
    <CheckUrlsToolRow activity={activity} defaultOpen={defaultOpen} />
  ),
}
